FROM ubuntu:24.04

# Install prerequisites
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y \
    lsb-release \
    software-properties-common \
    gnupg \
    curl \
    git \
    build-essential \
    cmake \
    ninja-build \
    python3 \
    python3-pip \
    python3-venv \
    wget

# Install LLVM 20
RUN wget https://apt.llvm.org/llvm.sh && \
    chmod +x llvm.sh && \
    ./llvm.sh 20 && \
    rm -rf llvm.sh

# Set up LLVM environment
RUN ln -s /usr/bin/clang-20 /usr/bin/clang && \
    ln -s /usr/bin/clang++-20 /usr/bin/clang++

# Set environment variables for LLVM
ENV CC=clang
ENV CXX=clang++

# Set Zig version and Install Path
ENV ZIG_VERSION=0.15.2
ENV ZIG_HOME=/opt/zig

# Install Zig
RUN curl -LO https://ziglang.org/download/${ZIG_VERSION}/zig-x86_64-linux-${ZIG_VERSION}.tar.xz && \
    tar -xf zig-x86_64-linux-${ZIG_VERSION}.tar.xz && \
    mv zig-x86_64-linux-${ZIG_VERSION} ${ZIG_HOME} && \
    ln -s ${ZIG_HOME}/zig /usr/bin/zig && \
    rm zig-x86_64-linux-${ZIG_VERSION}.tar.xz

# Build from the repository root so this image contains the checked-out client.
COPY Client /Verdict/Client
COPY LICENSE /Verdict/LICENSE

RUN python3 -m venv /.venv

ENV PATH="/.venv/bin:$PATH"

# Set the working directory to the Verdict Client
WORKDIR /Verdict/Client

RUN pip install --upgrade pip && \
    pip install -r requirements.txt

CMD ["sh", "-c", "exec python client.py --username \"${USERNAME:?Set USERNAME}\" --password \"${PASSWORD:?Set PASSWORD}\" --server \"${SERVER:?Set SERVER}\" --threads \"${THREADS:-auto}\" --nsockets \"${SOCKETS:-1}\" -I \"$(hostname)\""]
