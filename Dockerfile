FROM python:3.8.6-slim-buster
WORKDIR home
COPY ./requeriments.txt requirements.txt

 
RUN pip install -r requirements.txt --user

COPY app app
WORKDIR ./app
RUN export PYTHONPATH=$PWD:$PYTHONPATH 

ENTRYPOINT ["python"]
CMD ["main.py"]
