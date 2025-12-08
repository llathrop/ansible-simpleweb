FROM rockylinux:9

# Install system dependencies
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
COPY ansible.cfg ./

# Create logs directory
RUN mkdir -p /app/logs

# Create SSH directory for keys
RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh

# Expose Flask port
EXPOSE 3001

# Set environment variables
ENV FLASK_APP=web/app.py
ENV PYTHONUNBUFFERED=1

# Run Flask application
CMD ["python3", "-m", "flask", "run", "--host=0.0.0.0", "--port=3001"]
