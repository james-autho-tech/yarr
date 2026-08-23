ARG BUILD_FROM
FROM $BUILD_FROM

# Just AppDaemon itself plus the stdlib — everything yArr's
# core/clients/webui code needs, no extra solver/ML dependencies.
RUN pip3 install --no-cache-dir appdaemon==4.* pyyaml

COPY rootfs /
RUN chmod a+x \
    /etc/services.d/yarr/run /etc/services.d/yarr/finish \
    /etc/services.d/yarr-web/run /etc/services.d/yarr-web/finish

WORKDIR /opt/appdaemon
