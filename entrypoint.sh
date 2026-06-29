#!/bin/sh

echo "=== DIAGNOSTIC DES PERMISSIONS ==="
echo "Utilisateur courant : $(id)"
echo "Contenu récursif de /workspace :"
ls -R /workspace

echo "Test d'écriture sur le volume S3..."
if touch /workspace/test_write.txt; then
    echo "[SUCCÈS] Le conteneur peut écrire sur le volume S3 monté dans /workspace."
    rm /workspace/test_write.txt
else
    echo "[ÉCHEC] Impossible d'écrire sur le volume S3 dans /workspace (Permission denied ?)"
fi
echo "=================================="

# Modèle par défaut si non spécifié
MODEL_NAME=${MODEL_NAME:-"qwen3-coder:30b"}

# Extraire le nom du modèle et le tag
RAW_MODEL=$(echo "$MODEL_NAME" | cut -d: -f1)
TAG=$(echo "$MODEL_NAME" | cut -d: -f2)
if [ "$TAG" = "$RAW_MODEL" ]; then
    TAG="latest"
fi

# Déterminer le chemin du manifest
if echo "$RAW_MODEL" | grep -q "/"; then
    MANIFEST_PATH="/workspace/models/manifests/registry.ollama.ai/$RAW_MODEL/$TAG"
else
    MANIFEST_PATH="/workspace/models/manifests/registry.ollama.ai/library/$RAW_MODEL/$TAG"
fi

# Forcer Ollama à écouter localement sur le port interne 11430
export OLLAMA_HOST=127.0.0.1:11430

# Vérifier si le modèle est déjà présent dans le volume persistant
if [ ! -f "$MANIFEST_PATH" ]; then
    echo "Modèle '$MODEL_NAME' non trouvé ($MANIFEST_PATH), téléchargement en cours..."
    # Lancer ollama serve en arrière-plan pour le pull (écoute sur 11430)
    ollama serve &
    # Attendre que le serveur soit prêt
    sleep 10 
    # Télécharger le modèle spécifié (ollama pull utilise la variable OLLAMA_HOST=127.0.0.1:11430)
    ollama pull "$MODEL_NAME"
    # Arrêter le serveur temporaire pour redémarrer proprement
    pkill ollama
    sleep 2
else
    echo "Modèle '$MODEL_NAME' trouvé dans le stockage persistant."
fi

# Lancer Ollama en arrière-plan sur localhost:11430
echo "Démarrage du serveur Ollama local sur 127.0.0.1:11430..."
ollama serve &
sleep 8

# Pré-charger le modèle en mémoire (keep_alive: -1 le garde en VRAM indéfiniment)
echo "Pré-chargement du modèle '$MODEL_NAME' en mémoire..."
curl -s -X POST http://127.0.0.1:11430/api/chat -d "{\"model\": \"$MODEL_NAME\", \"messages\": [], \"keep_alive\": -1}"
echo ""
echo "Modèle pré-chargé avec succès !"

# Lancer le proxy de tool-calling sur le port public 11434 (PID 1 du conteneur)
echo "Démarrage du proxy de Tool-calling sur le port public 11434..."
exec python3 /usr/bin/ollama_tool_proxy.py --port 11434 --target http://127.0.0.1:11430