FROM ubuntu:bionic
RUN apt-get update && apt-get install --no-install-recommends -y \
    openssh-server \
    git \
    findutils \
    python3 \
    python3-pip \
    sudo \
    rsync \
    ca-certificates \
    gnupg2 \
    python3-setuptools \
    virtualenv \
    python3-venv
RUN mkdir /run/sshd
RUN useradd -d /home/zuul -m -u 1000 -U zuul
RUN echo "zuul  ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/zuul
RUN python3 -m venv /usr/os-testr-env && /usr/os-testr-env/bin/pip install os-testr
EXPOSE 22
CMD ["/usr/sbin/sshd", "-D"]
