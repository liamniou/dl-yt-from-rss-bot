FROM python:3.9.6

ARG user=lestar
ARG group=lestar
ARG uid=1000
ARG gid=1000
RUN groupadd -g ${gid} ${group}
RUN useradd -u ${uid} -g ${group} -s /bin/sh -m ${user}

# Switch to user
USER ${uid}:${gid}

WORKDIR /home/lestar

COPY ./req.txt ./

RUN pip install -r req.txt

COPY ./main.py ./

ENTRYPOINT ["python3"]

CMD ["main.py"]
