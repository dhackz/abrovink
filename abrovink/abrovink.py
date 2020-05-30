#!/usr/bin/python

# Copyright (C) 2020 Albin Vass.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
#
# See the License for the specific language governing permissions and
# limitations under the License.
import re
import os
import yaml
import copy
import pprint
import argparse
import traceback
import subprocess
import configparser

from pathlib import Path
from uuid import uuid4

pp = pprint.PrettyPrinter(indent=4)
zuul_test_keys = ""
zuul_test_root = ""
zuul_jobs_root = ""


class ZuulTest():

    jobs = dict()
    _unwrapped_jobs = dict()
    nodesets = dict()
    repo_root = None
    config_root = None
    _config = dict()

    def __init__(self):
        self.load_config()
        self.create_work_dir()
        self.populate_zuul_vars()
        self.load_zuul_items()
        self.probe_container_engine()

    def get_repo_root(self):
        cmd = ['git', 'rev-parse', '--show-toplevel']
        try:
            self.repo_root = Path(
                subprocess.check_output(cmd).decode().strip())
        except subprocess.CalledProcessError as e:
            print("Error: Not in a git repository")
            raise e
        os.chdir(self.repo_root)

    def load_config(self):
        self.get_repo_root()
        self.config_root = Path(self.repo_root, '.abrovink')
        with open(os.path.join(self.config_root, 'config.yaml'), 'r') as f:
            self._config = yaml.safe_load(f)

        self.canonical_name = self._config.get('canonical_name')
        self.src_dir = Path('src', self.canonical_name)

    def populate_zuul_vars(self):
        cmd = ['git', 'rev-parse', '--abbrev-ref', 'HEAD']
        self.branch = subprocess.check_output(cmd).decode().strip()
        cmd = ['git', 'log', '--format=%B', '-n', '1']
        self.commit_message = subprocess.check_output(cmd).decode().strip()

        self.project = dict(
            src_dir=str(self.src_dir),
            canonical_name=self.canonical_name,
            short_name=self.canonical_name.split("/")[-1],
            checkout=self.branch,
            required=False
        )
        self.zuul_vars = dict(
            build=str(uuid4().hex),
            buildset=str(uuid4().hex),
            branch=self.branch,
            change="1",
            patchset="1",
            change_url=str(self.work_dir),
            message=self.commit_message,
            pipeline="zuul-test",
            tenant="zuul-test",
            project=self.project,
            projects={self.canonical_name: self.project}
        )

    def create_work_dir(self):
        self.work_dir = Path(self.config_root, 'work')
        try:
            os.mkdir(self.work_dir)
        except FileExistsError:
            pass

    @property
    def zuul_paths(self):
        return self._config.get('zuul-paths', [])

    @property
    def controller_config(self):
        controller = self._config.get('controller')
        controller['build-context'] = Path(self.config_root,
                                           controller['build-context'])
        return self._config.get('controller')

    # TODO move path expansion to config load
    @property
    def labels(self):
        labels = self._config.get('labels')
        for label, config in labels.items():
            config['build-context'] = Path(self.config_root,
                                           config['build-context'])
        return labels

    @property
    def default_nodeset(self):
        return self._config.get('default-nodeset')

    # TODO load nodesets correctly
    def load_zuul_items(self):
        job_files = []
        for zuul_path in self.zuul_paths:
            for root, dirs, files in os.walk(zuul_path):
                for name in files:
                    job_files.append(Path(root, name))

        yaml_configs = []
        for f in job_files:
            with open(f, 'r') as f_h:
                try:
                    yaml_configs.extend(yaml.safe_load(f_h))
                except yaml.YAMLError as e:
                    print(e)

        for i in yaml_configs:
            if 'job' in i:
                self.jobs[i['job']['name']] = i['job']
            if 'nodeset' in i:
                self.nodesets[i['nodeset']['name']] = i['nodeset']

    def probe_container_engine(self):
        self.container_engine = 'docker'
        cmd = [self.container_engine, '--version']
        try:
            subprocess.check_output(cmd)
        except FileNotFoundError:
            self.container_engine = 'podman'
            cmd = [self.container_engine, '--version']
            try:
                subprocess.check_output(cmd)
            except subprocess.CalledProcessError as e:
                print("Error: No container engine installed")
                raise e

    # TODO simplify
    def _inherit(self, d, u):
        for k, v in u.items():
            if k not in d:
                d[k] = v
            elif k == 'post-run':
                if type(v) is list and type(d[k]) is list:
                    d[k] = [*v, *d[k]]
                elif type(v) is list and type(d[k]) is not list:
                    d[k] = [*v, d[k]]
                elif type(v) is not list and type(d[k]) is list:
                    d[k] = [v, *d[k]]
                elif type(v) is not list and type(d[k]) is not list:
                    d[k] = [v, d[k]]
            elif k == 'pre-run':
                if type(v) is list and type(d[k]) is list:
                    d[k].extend(v)
                elif type(v) is list and type(d[k]) is not list:
                    d[k] = [d[k], *v]
                elif type(v) is not list and type(d[k]) is list:
                    d[k].append(v)
                elif type(v) is not list and type(d[k]) is not list:
                    d[k] = [d[k], v]
            elif type(v) is dict:
                d[k] = self._inherit(d.get(k, {}), v)
            else:
                d[k] = v
        return d

    def _unwrap_job(self, name):
        if name not in self.jobs:
            return None
        parent_data = self._unwrap_job(self.jobs[name].get('parent'))
        data = dict()

        # Parent is in a different project return what we have
        if not parent_data:
            data = copy.deepcopy(self.jobs[name])
        # We have a parent in this project, update our data with
        # their data
        else:
            data = self._inherit(parent_data, self.jobs[name])
        return data

    def get_job(self, name):
        if name in self._unwrapped_jobs:
            return self._unwrapped_jobs[name]
        job = self._unwrap_job(name)
        print("Getting job nodeset: {}".format(job.get('nodeset')))
        if not job.get('nodeset'):
            job['nodeset'] = self.default_nodeset
        elif type(job.get('nodeset')) == str:
            job['nodeset'] = self.nodesets.get(job.get('nodeset'))
        print("Using nodeset: {}".format(job.get('nodeset')))
        self._unwrapped_jobs[name] = job
        return job


class Swarm():
    def __init__(self, work_root, container_engine,
                 controller_config, labels, nodesets):
        self.work_root = work_root
        self.container_engine = container_engine
        self.nodesets = nodesets
        self.labels = labels
        self.node_labels = set()
        self.nodes = []
        self.groups = []
        self.controller_config = controller_config
        self.controller = None
        self.workers = []

    def request(self, job):
        job_name = job.get('name')
        nodeset = job.get('nodeset')
        if type(nodeset) is str:
            self.nodes = self.nodesets.get(nodeset).get('nodes')
            self.groups = self.nodesets.get(nodeset).get('groups')
        elif type(nodeset) is dict:
            self.nodes = nodeset.get('nodes')
            self.groups = nodeset.get('groups')
        print("Found nodes: {}".format(self.nodes))

        # TODO update to match label_config and labels with a regex
        for node in self.nodes:
            self.node_labels.add(node.get('label'))

        self.build_images()
        self.launch_nodes(job_name)

    def build_images(self):
        print("Building node: controller")
        image_tag = 'zuul-test/controller'

        cmd = [
            self.container_engine,
            'build', self.controller_config.get('build-context'),
            '-t', image_tag
        ]
        print("Running: {}".format(cmd))
        subprocess.check_output(cmd)
        for node_label in self.node_labels:
            print("Building node_label: {}".format(node_label))
            if node_label not in self.labels:
                raise Exception("Label is not supported: %s" % node_label)
            label = self.labels.get(node_label)
            print("Building node: {}".format(node_label))

            image_tag = 'zuul-test/{}'.format(node_label)

            cmd = [
                self.container_engine,
                'build', label.get('build-context'),
                '-t', image_tag
            ]
            print("Running: {}".format(cmd))
            subprocess.check_output(cmd)

    def launch_nodes(self, job_name):
        self.workers = []
        name = "{}-{}".format(job_name, 'controller')
        self.controller = Controller(name,
                                     'zuul-test/controller',
                                     self.container_engine)
        for node in self.nodes:
            name = "{}-{}".format(job_name, node.get('name'))
            image = 'zuul-test/{}'.format(node.get('label'))
            worker = Worker(name,
                            image,
                            self.container_engine)
            self.workers.append(worker)

        for worker in self.workers:
            worker.launch()
        self.controller.launch()

        self.keypair = self.generate_ssh_keypair()
        self.controller.install_keypair(self.keypair)
        self.controller.authorize_key(self.keypair['public'])
        for worker in self.workers:
            worker.authorize_key(self.keypair['public'])
            # Add host key to known_hosts
            cmd = ['ssh', '-p', worker.port, '-o StrictHostKeyChecking=no',
                   'zuul@{}'.format(worker.hostname)]
            self.controller.exec(cmd, user='zuul')

    def generate_ssh_keypair(self):
        keypair = dict(
            public=Path('.zuul-test', 'work', "id_rsa.pub"),
            private=Path('.zuul-test', 'work', "id_rsa"),
        )

        try:
            keypair['public'].unlink()
        except FileNotFoundError:
            pass

        try:
            keypair['private'].unlink()
        except FileNotFoundError:
            pass

        cmd = ['ssh-keygen',
               '-t', 'rsa',
               '-f', str(keypair['private']),
               '-N', '']
        print("Running: {}".format(cmd))
        subprocess.check_output(cmd,
                                stderr=subprocess.STDOUT)
        return keypair

    def stop(self):
        for worker in self.workers:
            worker.terminate()
        if self.controller:
            self.controller.terminate()


class Worker():
    def __init__(self, name, image, container_engine):
        self.name = name
        self.image = image
        self.container_engine = container_engine
        self.running = False

    def launch(self):
        cmd = ['run',
               '-d', '-P',
               '--name', self.name,
               self.image]
        self.command(cmd)

        cmd = ['port', self.name]
        output = self.command(cmd)
        self.port = re.search(
            r'22/tcp -> 0.0.0.0:(\d+)',
            output).group(1)
        cmd = ['hostname']
        self.hostname = subprocess.check_output(cmd).decode().strip()
        self.running = True

    # TODO configurable user
    def authorize_key(self, ssh_public_key):
        self.exec(['mkdir', '-p', '/home/zuul/.ssh'])
        self.copy(str(ssh_public_key), "/tmp/ssh.pub")
        self.exec(['sh', '-c',
                   'cat /tmp/ssh.pub >> /home/zuul/.ssh/authorized_keys'])
        self.exec(['chown', '-R', 'zuul:zuul', '/home/zuul/.ssh'])
        self.exec(['chmod', '600', '/home/zuul/.ssh/authorized_keys'])

    def copy(self, src, dest, *flags, push=True):
        cmd = ['cp']
        if flags:
            cmd.extend(flags)

        if push:
            cmd.extend([src, "{}:{}".format(self.name, dest)])
        else:
            cmd.extend(["{}:{}".format(self.name, src), dest])

        try:
            self.command(cmd)
        except subprocess.CalledProcessError as e:
            raise e

    def terminate(self):
        cmd = ['rm', '-f', self.name]
        try:
            self.command(cmd)
        except subprocess.CalledProcessError:
            pass
        self.running = False

    def command(self, subcmd):
        cmd = [self.container_engine, *subcmd]
        print("Running: {}".format(cmd))
        output = ""
        p = subprocess.Popen(cmd,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             universal_newlines=True)
        running = True
        while running:
            stdout = p.stdout.readline()
            if p.poll() is not None:
                running = False
            if stdout:
                print(stdout, end='')
                output += stdout
        if p.returncode != 0:
            raise subprocess.CalledProcessError(p, cmd)
        return output

    # TODO root=False
    def exec(self, subcmd, workdir=None, user=None, env=None):
        cmd = ['exec']
        if user:
            cmd.extend(['-u', user])
        if workdir:
            cmd.extend(['-w', workdir])
        if env:
            for k, v in env.items():
                cmd.extend(['-e', '{}={}'.format(k, v)])
        cmd.extend([self.name, *subcmd])
        self.command(cmd)


# TODO bind mount output directory
class Controller(Worker):

    def install_keypair(self, keypair):
        self.keypair = keypair
        self.exec(['mkdir', '-p', '/home/zuul/.ssh'])
        self.copy(str(keypair['private']), "/home/zuul/.ssh/id_rsa")
        self.exec(['chown', 'zuul:zuul', '/home/zuul/.ssh/id_rsa'])
        self.exec(['chmod', '600', '/home/zuul/.ssh/id_rsa'])

        self.copy(str(keypair['public']), "/home/zuul/.ssh/id_rsa.pub")
        self.exec(['chown', 'zuul:zuul', '/home/zuul/.ssh/id_rsa.pub'])
        self.exec(['chmod', '600', '/home/zuul/.ssh/id_rsa.pub'])

    def setup_workdir(self, src_dir):
        self.work_root = Path('/home/zuul')
        self.log_root = Path(self.work_root, 'logs')
        self.src_dir = src_dir
        self.repo_root = Path(self.work_root, self.src_dir)
        ssh_command = "ssh -p {} -i {}".format(
            self.port,
            self.keypair['private'])

        self.exec(['mkdir', '-p', self.log_root], user='zuul')
        self.exec(['mkdir', '-p', self.repo_root], user='zuul')

        # We don't care about the controllers host key
        # and we don't want to pollute the users known_hosts
        # so don't check the host key or save it
        ssh_command += " -o StrictHostKeyChecking=no"
        ssh_command += " -o UserKnownHostsFile=/dev/null"
        cmd = ['rsync',
               '-e', ssh_command,
               '--filter=:- .gitignore',
               '--exclude=".git"',
               '--links',
               '-r',
               '.', 'zuul@localhost:{}'.format(self.repo_root)]
        print("Running: {}".format(cmd))
        subprocess.check_output(cmd)
        self.copy(str(Path('.git').resolve()), Path(self.repo_root, '.git'))
        self.exec(['chown', '-R', 'zuul:zuul', Path(self.repo_root, '.git')])

        try:
            self.exec(['git', 'diff', '--quiet'],
                      workdir=self.repo_root,
                      user='zuul')
        except subprocess.CalledProcessError:
            self.exec(['git', 'config', 'user.name', 'zuul-test'],
                      workdir=self.repo_root,
                      user='zuul')
            self.exec(['git', 'config', 'user.email', 'zuul-test@zuul-ci.org'],
                      workdir=self.repo_root,
                      user='zuul')
            self.exec(['git', 'add', '.'],
                      workdir=self.repo_root,
                      user='zuul')
            self.exec(['git', 'commit', '-m', 'zuul-test: wip commit'],
                      workdir=self.repo_root,
                      user='zuul')

        self.build_ansible_config()
        self.zuul_vars = dict(
            executor=dict(
                hostname=self.hostname,
                src_root=str(Path(self.work_root, 'src')),
                work_root=str(self.work_root),
                log_root=str(self.log_root),
                inventory_file=str(Path(self.work_root, 'hosts.yaml'))
            )
        )

    def build_ansible_config(self):
        self.fact_cache = Path(self.work_root, 'cache')
        self.exec(['mkdir', '-p',
                   str(self.fact_cache)], user='zuul')
        ansible_cfg = configparser.ConfigParser()
        ansible_cfg['defaults'] = {}
        ansible_cfg['defaults']['fact_caching'] = 'jsonfile'
        ansible_cfg['defaults']['fact_caching_connection'] = str(
            self.fact_cache)
        self.ansible_cfg = Path('.zuul-test', 'work', 'ansible.cfg')
        with self.ansible_cfg.open('w') as f:
            ansible_cfg.write(f)
        self.copy(str(self.ansible_cfg),
                  str(Path(self.work_root, 'ansible.cfg')))


class ZuulJob():
    def __init__(self, job, zuul_vars, controller, workers, work_dir):
        self.job = job
        self.controller = controller
        self.zuul_vars = copy.deepcopy(zuul_vars)
        self.zuul_vars.update({'job': self.job.get('name')})
        self.zuul_vars.update(self.controller.zuul_vars)
        self.workers = workers
        self.work_dir = work_dir

    def build_inventory(self):
        cmd = ['hostname']
        hostname = subprocess.check_output(cmd).decode().strip()

        hosts = dict()
        for worker in self.workers:
            hosts[worker.name] = dict(
                ansible_user="zuul",
                ansible_host=hostname,
                ansible_port=worker.port,
            )
        inventory = dict(all=dict(hosts=hosts))

        inventory['all']['vars'] = dict(
            zuul=self.zuul_vars
        )
        inventory['all']['vars'].update(self.job.get('vars', {}))
        self.inventory_file = Path(self.work_dir, 'hosts.yaml')
        with self.inventory_file.open('w') as f:
            yaml.dump(inventory, f, default_flow_style=False)
        self.controller.copy(str(self.inventory_file), '/home/zuul/hosts.yaml')

    # TODO correctly handle pre-run/run/post-run
    def run_job(self):
        pp.pprint(self.job)

        setup = '.zuul-test/setup.yaml'
        run = self.job.get('run')

        pre_runs = self.job.get('pre-run', [])
        if type(pre_runs) != list:
            pre_runs = [pre_runs]

        post_runs = self.job.get('post-run', [])
        if type(post_runs) != list:
            post_runs = [post_runs]

        cleanup_runs = self.job.get('cleanup-run', [])
        if type(cleanup_runs) != list:
            cleanup_runs = [cleanup_runs]

        if not self.run_ansible(setup):
            raise Exception("Zuul-test setup failed")

        zuul_success = True
        for pre_run in pre_runs:
            zuul_success = self.run_ansible(pre_run)
            if not zuul_success:
                break

        if zuul_success:
            zuul_success = self.run_ansible(run)

        for post_run in post_runs:
            zuul_success = zuul_success and self.run_ansible(
                post_run,
                extra_vars={'zuul_success': zuul_success})

        for cleanup_run in cleanup_runs:
            self.run_ansible(cleanup_run,
                             extra_vars={'zuul_success': zuul_success})
        return zuul_success

    def run_ansible(self, playbook, extra_vars=None):
        inventory = os.path.join('/home/zuul/', 'hosts.yaml')
        print(playbook)
        cmd = ['/home/zuul/.local/bin/ansible-playbook', '-i', inventory,
               os.path.join('/home/zuul', self.controller.src_dir, playbook),
               '-vv']
        if extra_vars:
            for k, v in extra_vars.items():
                cmd.extend(['-e{}={}'.format(k, v)])
        environment = dict()
        environment.update(
            {'ANSIBLE_ROLES_PATH': '{}/roles'.format(
                Path('/home/zuul', self.controller.src_dir))})
        environment.update(
            {'ANSIBLE_LIBRARY': '{}/tests/fake-ansible'.format(
                Path('/home/zuul', self.controller.src_dir))})
        environment.update({'ANSIBLE_FORCE_COLOR': 'True'})
        environment.update({'ANSIBLE_CONFIG': '/home/zuul/ansible.cfg'})
        try:
            self.controller.exec(cmd, user='zuul', env=environment)
        except subprocess.CalledProcessError:
            return False
            pass
        return True

    def run(self):
        self.build_inventory()
        return self.run_job()


# TODO add --nodeset to override nodeset
def parse_args():
    parser = argparse.ArgumentParser()
    subparser = parser.add_subparsers(title='commands')

    cmd_run = subparser.add_parser('run')
    cmd_run.add_argument('jobs', metavar='JOB', type=str, nargs='+')
    cmd_run.add_argument('--no-terminate', action='store_true')
    cmd_run.set_defaults(command='run')

    cmd_list = subparser.add_parser('list')
    cmd_list.set_defaults(command='list')
    return parser.parse_args()


# TODO add support for ansible debugging
# TODO add support for ansible --step
# TODO use zuul's ansible modules
# TODO add logging
def main():
    args = parse_args()

    zuul_test = ZuulTest()

    if args.command == 'list':
        for job in zuul_test.jobs.keys():
            print(job)
    elif args.command == 'run':
        swarm = Swarm(zuul_test.create_work_dir(),
                      zuul_test.container_engine,
                      zuul_test.controller_config,
                      zuul_test.labels,
                      zuul_test.nodesets)

        jobs = args.jobs
        job_results = dict()
        for job in jobs:
            result = False
            try:
                swarm.request(zuul_test.get_job(job))
                swarm.controller.setup_workdir(zuul_test.src_dir)
                zuul_job = ZuulJob(zuul_test.get_job(job),
                                   zuul_test.zuul_vars,
                                   swarm.controller,
                                   swarm.workers,
                                   zuul_test.work_dir)
                result = zuul_job.run()
            except Exception:
                traceback.print_exc()
            finally:
                if not args.no_terminate:
                    swarm.stop()
            job_results[job] = result
        for name, result in job_results.items():
            print("{}: {}".format(name, result))


if __name__ == '__main__':
    main()
