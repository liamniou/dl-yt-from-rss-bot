FROM python:3.9.6

WORKDIR /app

COPY ./req.txt ./

RUN pip install -r req.txt

COPY ./main.py ./

ENTRYPOINT ["python3"]

CMD ["main.py"]
