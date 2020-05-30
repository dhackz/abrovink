FROM fedora:latest
RUN dnf install -y \
    openssh-server \
    rsync \
    git \
    pip \
    rsync
RUN ssh-keygen -t dsa -f /etc/ssh/ssh_host_dsa_key -t dsa -N ''
RUN ssh-keygen -t rsa -f /etc/ssh/ssh_host_rsa_key -t rsa -N ''
RUN useradd -d /home/zuul -m -u 1000 -U zuul
RUN echo "zuul  ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/zuul
RUN mkdir /home/zuul/.ssh && \
    chmod 700 /home/zuul/.ssh && \
    chown -R zuul:zuul /home/zuul/.ssh
EXPOSE 22
USER zuul
# TODO use supported ansible version
RUN pip install --user ansible netaddr
USER root
CMD ["/sbin/sshd", "-D"]
