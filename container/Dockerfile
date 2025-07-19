From python:3.10-slim 

WORKDIR /app 

COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY aprs.py .
COPY templates/ templates/ 
COPY aprschat.config .

EXPOSE 5001 

CMD ["python", "app.py"]
