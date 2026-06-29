FROM ollama/ollama:latest

# Utiliser root pour installer les paquets système
USER root

# Installer python3 et python3-requests
RUN apt-get update && apt-get install -y python3 python3-requests && rm -rf /var/lib/apt/lists/*

# Création des dossiers requis avec les droits pour l'utilisateur OVH (42420)
RUN mkdir -p /workspace /tmp/.ollama && \
    chown -R 42420:42420 /workspace /tmp /tmp/.ollama

# Variables d'environnement
ENV HOME=/tmp
ENV OLLAMA_MODELS=/workspace/models
ENV OLLAMA_HOST=0.0.0.0

# Copier le proxy de Tool-calling Ollama
COPY ollama_tool_proxy.py /usr/bin/ollama_tool_proxy.py
RUN chmod +x /usr/bin/ollama_tool_proxy.py

# Copie d'un script d'initialisation (on va le créer juste après)
COPY entrypoint.sh /usr/bin/entrypoint.sh
RUN chmod +x /usr/bin/entrypoint.sh

EXPOSE 11434

USER 42420:42420

# Utiliser le script comme point d'entrée
ENTRYPOINT ["/usr/bin/entrypoint.sh"]