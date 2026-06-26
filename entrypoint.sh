#!/bin/sh

echo "=== DIAGNOSTIC DES PERMISSIONS ==="
echo "Utilisateur courant : $(id)"
echo "Contenu et droits de /workspace :"
ls -la /workspace

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

# Vérifier si le modèle est déjà présent dans le volume persistant
if [ ! -f "$MANIFEST_PATH" ]; then
    echo "Modèle '$MODEL_NAME' non trouvé ($MANIFEST_PATH), téléchargement en cours..."
    # Lancer ollama serve en arrière-plan pour le pull
    ollama serve &
    # Attendre que le serveur soit prêt
    sleep 10 
    # Télécharger le modèle spécifié
    ollama pull "$MODEL_NAME"
    # Arrêter le serveur temporaire pour redémarrer proprement
    pkill ollama
    sleep 2
else
    echo "Modèle '$MODEL_NAME' trouvé dans le stockage persistant."
fi

# Lancer Ollama normalement
echo "Démarrage du serveur Ollama..."
exec ollama serve