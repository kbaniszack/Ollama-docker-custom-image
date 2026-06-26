FROM ollama/ollama:latest

# Création des dossiers requis avec les droits pour l'utilisateur OVH (42420)
RUN mkdir -p /workspace /tmp/.ollama && \
    chown -R 42420:42420 /workspace /tmp /tmp/.ollama

# Variables d'environnement
ENV HOME=/tmp
ENV OLLAMA_MODELS=/workspace/models
ENV OLLAMA_HOST=0.0.0.0

# Copie d'un script d'initialisation (on va le créer juste après)
COPY entrypoint.sh /usr/bin/entrypoint.sh
RUN chmod +x /usr/bin/entrypoint.sh

EXPOSE 11434

USER 42420:42420

# Utiliser le script comme point d'entrée
ENTRYPOINT ["/usr/bin/entrypoint.sh"]