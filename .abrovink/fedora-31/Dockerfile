FROM fedora:31
RUN dnf install -y \
    openssh-server \
    git \
    findutils \
    gnupg2 \
    rsync \
    python3-setuptools \
    virtualenv \
    'dnf-command(copr)' \
    xz \
    make
RUN ssh-keygen -t dsa -f /etc/ssh/ssh_host_dsa_key -N ''
RUN ssh-keygen -t rsa -f /etc/ssh/ssh_host_rsa_key -N ''
RUN useradd -d /home/zuul -m -u 1000 -U zuul
RUN echo "zuul  ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/zuul
RUN python3 -m venv /usr/os-testr-env && /usr/os-testr-env/bin/pip install os-testr
EXPOSE 22
CMD ["/sbin/sshd", "-D"]
