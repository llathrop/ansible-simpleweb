FROM rockylinux:9

# Install system dependencies
# Note: stdbuf is included in coreutils-single which comes with the base image
RUN dnf update -y && \
    dnf install -y \
    python3 \
    python3-pip \
    openssh-clients \
    sshpass \
    git \
    && dnf clean all

# Install Ansible via pip
RUN pip3 install --no-cache-dir ansible

# Create app directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application files
COPY web/ ./web/
COPY playbooks/ ./playbooks/
COPY inventory/ ./inventory/
COPY library/ ./library/
COPY callback_plugins/ ./callback_plugins/
COPY ansible.cfg ./
COPY run-playbook.sh ./
COPY gunicorn_config.py ./

# Make run script executable
RUN chmod +x /app/run-playbook.sh

# Create logs directory
RUN mkdir -p /app/logs

# Create SSH directory for keys
RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh

# Expose ports (HTTP and HTTPS)
EXPOSE 3001
EXPOSE 3443

# Create certificates directory
RUN mkdir -p /app/config/certs && chmod 755 /app/config/certs

# Set environment variables
ENV FLASK_APP=web/app.py
ENV PYTHONUNBUFFERED=1

# Default to development mode (direct python)
# For production with SSL, use: gunicorn -c gunicorn_config.py web.app:app
CMD ["python3", "web/app.py"]
