FROM python:3
ARG YANG_ID
ARG YANG_GID

ENV YANG_ID "$YANG_ID"
ENV YANG_GID "$YANG_GID"
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONUNBUFFERED=1

ENV VIRTUAL_ENV=/backend

#Install Cron
RUN apt-get update
RUN apt-get -y install nodejs libv8-dev ruby-full cron uwsgi uwsgi-plugin-python3 logrotate \
  && apt-get autoremove -y

RUN gem install bundler

RUN groupadd -g ${YANG_GID} -r yang \
  && useradd --no-log-init -r -g yang -u ${YANG_ID} -d $VIRTUAL_ENV yang \
  && pip install virtualenv \
  && virtualenv --system-site-packages $VIRTUAL_ENV \
  && mkdir -p /etc/yangcatalog

COPY . $VIRTUAL_ENV

ENV PYTHONPATH=$VIRTUAL_ENV/bin/python
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV GIT_PYTHON_GIT_EXECUTABLE=/usr/bin/git

WORKDIR $VIRTUAL_ENV

RUN pip install -r requirements.txt \
  && ./setup.py install

ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV UWSGI_PROCS=1
ENV UWSGI_THREADS=20

# Add crontab file in the cron directory
COPY crontab /etc/cron.d/yang-cron

COPY yang-catalog.ini-dist $VIRTUAL_ENV/yang-catalog.ini
RUN mkdir /var/run/yang

RUN chown yang:yang /etc/cron.d/yang-cron
RUN chown -R yang:yang $VIRTUAL_ENV
RUN chown -R yang:yang /var/run/yang

RUN mkdir /var/run/mysqld
RUN chown -R yang:yang /var/run/mysqld
RUN chmod 777 /var/run/mysqld

COPY yangcatalog-rotate /etc/logrotate.d/yangcatalog-rotate

USER ${YANG_ID}:${YANG_GID}

RUN git clone https://github.com/slatedocs/slate.git

WORKDIR $VIRTUAL_ENV/slate

RUN rm -rf source
RUN cp -R ../documentation/source .

WORKDIR $VIRTUAL_ENV

# Apply cron job
RUN crontab /etc/cron.d/yang-cron

USER root:root
WORKDIR $VIRTUAL_ENV/slate
RUN bundle install
CMD bundle exec middleman build --clean
WORKDIR $VIRTUAL_ENV
CMD cp -R $VIRTUAL_ENV/slate /usr/share/nginx/html
CMD chown -R yang:yang /var/run/yang && cron && uwsgi --ini $VIRTUAL_ENV/yang-catalog.ini

EXPOSE 3031
