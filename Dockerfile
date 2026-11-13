FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py workspace.py git_workflow.py sandbox_runner.py terminal_sessions.py relay_manager.py ddns.py micro_firewall.py network_connectivity.py mdns_service.py computer_use_manager.py ./
COPY static ./static

RUN mkdir -p /app/data /app/shared_files
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
