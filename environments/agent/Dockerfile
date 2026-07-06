FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99

# 1) Install Xfce, x11vnc, Xvfb, xdotool, xclip, curl, Python, pip, etc., but remove any screen lockers or power managers
RUN apt-get update && apt-get install -y \
    xfce4 \
    xfce4-goodies \
    x11vnc \
    xvfb \
    xdotool \
    xclip \
    imagemagick \
    x11-apps \
    sudo \
    software-properties-common \
    imagemagick \
    curl \
    python3 \
    python3-pip \
    && apt-get remove -y light-locker xfce4-screensaver xfce4-power-manager || true \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 2) Add the mozillateam PPA and install Firefox ESR
RUN add-apt-repository ppa:mozillateam/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends firefox-esr \
    && update-alternatives --set x-www-browser /usr/bin/firefox-esr \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 3) Create non-root user
RUN useradd -ms /bin/bash myuser \
    && echo "myuser ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
USER myuser
WORKDIR /home/myuser

# 4) Set x11vnc password ("secret")
RUN x11vnc -storepasswd secret /home/myuser/.vncpass

# 5) Expose port 5901 and run Xvfb, x11vnc, Xfce (no login manager)
EXPOSE 5901
CMD ["/bin/sh", "-c", "rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null; export DISPLAY=:99 && Xvfb :99 -screen 0 1280x800x24 -ac +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 & sleep 2 && x11vnc -display :99 -forever -rfbauth /home/myuser/.vncpass -listen 0.0.0.0 -rfbport 5901 >/tmp/x11vnc.log 2>&1 & startxfce4 >/tmp/xfce.log 2>&1 & sleep 3 && echo 'Container running!' && tail -f /dev/null"]
