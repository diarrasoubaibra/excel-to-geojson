# 🌳 Convertisseur Kobo → GeoJSON de polygones

Application web qui convertit un export **Excel KoboToolbox** (ou un GeoJSON
mixte) en fichier GeoJSON contenant **uniquement les polygones de parcelles**,
prêt à charger dans le système d'analyse.

Aucune compétence technique requise pour l'utilisateur final : il dépose son
fichier, il télécharge le résultat.

## Ce que fait l'application

- Détecte automatiquement les colonnes de tracé (geoshape) et de point GPS
  (geopoint), même si le formulaire Kobo change de libellés
- Reconstruit **tous** les polygones depuis l'Excel (l'export GeoJSON de Kobo
  peut en perdre — l'Excel, jamais)
- Referme les anneaux mal fermés et écarte les tracés invalides
- Signale nommément les enquêtes **sans tracé** (à re-cartographier)
- Affiche un récapitulatif (surfaces GPS par parcelle) et une carte
- Boutons de téléchargement : fichier POLYGONES (pour le système) et
  fichier POINTS (pour vérification / QGIS)

## Déploiement sur Streamlit Cloud (gratuit)

1. Créer un compte sur https://github.com (si pas déjà fait)
2. Créer un nouveau dépôt (par ex. `kobo-geojson`) et y déposer ces
   2 fichiers : `app.py` et `requirements.txt`
3. Aller sur https://share.streamlit.io et se connecter avec GitHub
4. Cliquer **New app** → choisir le dépôt → *Main file path* : `app.py`
   → **Deploy**
5. Après ~2 minutes, l'application est en ligne à une adresse du type
   `https://kobo-geojson.streamlit.app` — c'est ce lien qu'il faut
   partager avec les utilisateurs

## Test en local (facultatif)

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Mode d'emploi pour l'utilisateur final

1. Dans KoboToolbox : **Données → Exporter → XLS** (avec les labels)
2. Ouvrir l'application et **déposer le fichier Excel**
3. Vérifier le résumé (nombre de polygones, enquêtes sans tracé)
4. Cliquer **⬇️ Fichier POLYGONES** et charger ce fichier dans le système
