# -*- coding: utf-8 -*-
"""
Convertisseur de données géospatiales -> GeoJSON de polygones
Application Streamlit prête pour Streamlit Cloud.

Accepte tout export Excel ou GeoJSON contenant des colonnes de type
geoshape / geopoint (formulaires ODK/KoboToolbox, QGIS, ArcGIS, etc.).

Déploiement :
  1. Mettre app.py et requirements.txt dans un dépôt GitHub
  2. Sur share.streamlit.io : New app -> choisir le dépôt -> fichier principal : app.py
"""
import io
import json
import math
import re

import pandas as pd

# ----------------------------------------------------------------------------
# LOGIQUE DE CONVERSION (indépendante de Streamlit)
# ----------------------------------------------------------------------------

MOTIF_GEOSHAPE = re.compile(
    r"^\s*-?\d{1,3}\.\d+\s+-?\d{1,3}\.\d+(\s+-?\d+(\.\d+)?){0,2}\s*"
    r"(;\s*-?\d{1,3}\.\d+\s+-?\d{1,3}\.\d+(\s+-?\d+(\.\d+)?){0,2}\s*){2,}$"
)
MOTIF_GEOPOINT = re.compile(
    r"^\s*-?\d{1,3}\.\d+\s+-?\d{1,3}\.\d+(\s+-?\d+(\.\d+)?){0,2}\s*$"
)

NOMS_SHAPE = ["délimitation", "delimitation", "tracé", "trace", "contour",
              "polygon", "zone", "geoshape", "parcelle"]
NOMS_POINT = ["waypoint", "point gps", "geopoint", "localisation", "position",
              "coordonnées", "coordonnees"]


def detecter_colonne(df, motif, noms_probables):
    for nom in noms_probables:
        for col in df.columns:
            if nom.lower() in str(col).lower():
                serie = df[col].dropna().astype(str)
                if len(serie) and serie.head(20).apply(
                        lambda v: bool(motif.match(v))).mean() > 0.5:
                    return col
    for col in df.columns:
        serie = df[col].dropna().astype(str)
        if len(serie) >= 3 and serie.head(20).apply(
                lambda v: bool(motif.match(v))).mean() > 0.8:
            return col
    return None


def parser_anneau(texte):
    anneau = []
    for morceau in str(texte).strip().split(";"):
        valeurs = morceau.split()
        if len(valeurs) >= 2:
            lat, lon = float(valeurs[0]), float(valeurs[1])
            anneau.append([lon, lat])
    if anneau and anneau[0] != anneau[-1]:
        anneau.append(list(anneau[0]))
    return anneau


def surface_ha(anneau):
    if len(anneau) < 4:
        return 0.0
    lat0 = math.radians(sum(p[1] for p in anneau) / len(anneau))
    R = 6371008.8
    xs = [math.radians(p[0]) * R * math.cos(lat0) for p in anneau]
    ys = [math.radians(p[1]) * R for p in anneau]
    a = sum(xs[i] * ys[i + 1] - xs[i + 1] * ys[i] for i in range(len(anneau) - 1))
    return abs(a) / 2 / 10000


def valeur_propre(valeur):
    if valeur is None or (isinstance(valeur, float) and math.isnan(valeur)):
        return None
    if hasattr(valeur, "isoformat"):
        return valeur.isoformat()
    if isinstance(valeur, (int, float, str, bool)):
        return valeur
    return str(valeur)


def identifiant(props, defaut):
    for cle in props:
        k = str(cle).lower()
        if ("nom" in k and ("producteur" in k or "beneficiaire" in k or "bénéficiaire" in k)):
            if props[cle]:
                return str(props[cle])
    return props.get("_uuid") or defaut


def convertir_excel(contenu_bytes):
    """Convertit un export Excel (colonnes geoshape/geopoint). Retourne un dict de résultats."""
    df = pd.read_excel(io.BytesIO(contenu_bytes))
    col_shape = detecter_colonne(df, MOTIF_GEOSHAPE, NOMS_SHAPE)
    col_point = detecter_colonne(df, MOTIF_GEOPOINT, NOMS_POINT)

    res = {"nb_lignes": len(df), "col_shape": col_shape, "col_point": col_point,
           "polygones": [], "points": [], "sans_trace": [], "anomalies": [],
           "tableau": []}
    if col_shape is None:
        res["erreur"] = ("Aucune colonne de tracé (geoshape) n'a été détectée. "
                        "Vérifiez que l'export Excel contient bien la colonne de "
                        "délimitation de parcelle.")
        return res

    for _, ligne in df.iterrows():
        props = {str(c): valeur_propre(ligne[c]) for c in df.columns if c != col_shape}
        props = {k: v for k, v in props.items() if v is not None}
        ident = identifiant(props, f"ligne {ligne.name + 2}")
        village = next((props[c] for c in props if "village" in str(c).lower()), "")

        brut = ligne[col_shape]
        aire = None
        statut = "OK"
        if pd.isna(brut):
            res["sans_trace"].append({"Producteur": ident, "Village": village})
            statut = "SANS TRACÉ"
        else:
            anneau = parser_anneau(brut)
            if len(anneau) < 4:
                res["anomalies"].append(f"{ident} : tracé avec moins de 3 sommets, ignoré")
                statut = "TRACÉ INVALIDE"
            else:
                aire = surface_ha(anneau)
                if aire < 0.01:
                    res["anomalies"].append(
                        f"{ident} : polygone minuscule ({aire * 10000:.0f} m²), à vérifier")
                    statut = "MINUSCULE"
                res["polygones"].append({
                    "type": "Feature", "properties": props,
                    "geometry": {"type": "Polygon", "coordinates": [anneau]},
                })

        if col_point is not None and not pd.isna(ligne.get(col_point)):
            vals = str(ligne[col_point]).split()
            try:
                lat, lon = float(vals[0]), float(vals[1])
                res["points"].append({
                    "type": "Feature", "properties": props,
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                })
            except (ValueError, IndexError):
                pass

        res["tableau"].append({
            "Producteur": ident, "Village": village,
            "Surface GPS (ha)": round(aire, 2) if aire is not None else None,
            "Statut": statut,
        })
    return res


def convertir_geojson(contenu_bytes):
    """Sépare un GeoJSON mixte : garde les polygones, met les points à part."""
    data = json.loads(contenu_bytes.decode("utf-8"))
    feats = data.get("features", [])
    res = {"nb_lignes": len(feats), "polygones": [], "points": [],
           "sans_trace": [], "anomalies": [], "tableau": [],
           "col_shape": "géométries GeoJSON", "col_point": None}
    for feat in feats:
        g = feat.get("geometry") or {}
        props = feat.get("properties", {})
        ident = identifiant(props, "?")
        village = next((props[c] for c in props if "village" in str(c).lower()), "")
        if g.get("type") in ("Polygon", "MultiPolygon"):
            rings = (g["coordinates"] if g["type"] == "Polygon"
                     else [r for poly in g["coordinates"] for r in poly])
            for ring in rings:
                if ring and ring[0] != ring[-1]:
                    ring.append(list(ring[0]))
            res["polygones"].append(feat)
            aire = surface_ha([(p[0], p[1]) for p in rings[0]]) if rings else 0
            res["tableau"].append({"Producteur": ident, "Village": village,
                                   "Surface GPS (ha)": round(aire, 2), "Statut": "OK"})
        elif g.get("type") in ("Point", "MultiPoint"):
            res["points"].append(feat)

    # signaler les enquêtes qui n'existent que sous forme de point
    def cle(f):
        return f.get("properties", {}).get("_uuid") or id(f)
    uuids_poly = {cle(f) for f in res["polygones"]}
    for f in res["points"]:
        if cle(f) not in uuids_poly:
            p = f.get("properties", {})
            res["sans_trace"].append({
                "Producteur": identifiant(p, "?"),
                "Village": next((p[c] for c in p if "village" in str(c).lower()), ""),
            })
    return res


def en_geojson_bytes(features, nom):
    fc = {"type": "FeatureCollection", "name": nom, "features": features}
    return json.dumps(fc, ensure_ascii=False).encode("utf-8")


# ----------------------------------------------------------------------------
# INTERFACE STREAMLIT
# ----------------------------------------------------------------------------

DEV_NOM = "Ibrahim Diarrassouba"
DEV_EMAIL = "ibrahimdiarrassouba840@gmail.com"
DEV_TEL = "+225 07 68 14 04 13"
DEV_TEL_LIEN = "+2250768140413"


def afficher_barre_laterale():
    import streamlit as st

    with st.sidebar:
        st.markdown("##### :material/info: À propos de l'outil")
        st.caption(
            "Convertit un export **Excel** ou **GeoJSON** issu de n'importe "
            "quel outil de collecte de terrain (ODK, KoboToolbox, QGIS, "
            "ArcGIS…) en fichiers GeoJSON de **polygones** et de **points**, "
            "prêts à charger dans un SIG."
        )

        st.space("small")
        st.markdown("##### :material/person: Développeur")
        st.write(f"**{DEV_NOM}**")
        st.markdown(f":material/mail: [{DEV_EMAIL}](mailto:{DEV_EMAIL})")
        st.markdown(f":material/call: [{DEV_TEL}](tel:{DEV_TEL_LIEN}) · WhatsApp")
        st.badge("Disponible sur demande", icon=":material/check_circle:", color="green")
        st.caption(
            "Une question, un besoin précis ou une évolution à envisager ? "
            "N'hésitez pas à me contacter par e-mail, appel ou WhatsApp."
        )


def main():
    import streamlit as st

    st.set_page_config(page_title="Convertisseur géospatial",
                       page_icon=":material/travel_explore:", layout="wide")

    afficher_barre_laterale()

    st.title(":material/travel_explore: Convertisseur de données géospatiales")
    st.markdown(
        "Déposez un **export Excel** (formulaire ODK/KoboToolbox ou tout "
        "tableur avec des colonnes de tracé GPS) ou un fichier **GeoJSON** : "
        "l'application isole les **polygones de parcelles**, prêts à charger "
        "dans votre système, et signale les enquêtes incomplètes."
    )

    fichier = st.file_uploader(
        "Déposer le fichier ici",
        type=["xlsx", "xls", "geojson", "json"],
        help="Export Excel (colonnes geoshape/geopoint) ou export GeoJSON",
    )

    if fichier is None:
        st.info(
            "**Conseil** : préférez l'export **Excel**. Certains outils de "
            "collecte perdent des polygones lors de l'export direct en "
            "GeoJSON, alors que l'Excel contient toujours tous les tracés.",
            icon=":material/lightbulb:",
        )
        return

    contenu = fichier.read()
    try:
        with st.spinner("Analyse du fichier en cours…"):
            if fichier.name.lower().endswith((".xlsx", ".xls")):
                res = convertir_excel(contenu)
            else:
                res = convertir_geojson(contenu)
    except Exception as e:
        st.error(f"Impossible de lire ce fichier : {e}", icon=":material/error:")
        return

    if res.get("erreur"):
        st.error(res["erreur"], icon=":material/error:")
        return

    # --- Résumé -------------------------------------------------------------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Enquêtes", res["nb_lignes"])
    c2.metric("Polygones valides", len(res["polygones"]))
    c3.metric("Points GPS", len(res["points"]))
    c4.metric("Sans tracé", len(res["sans_trace"]),
              delta=None if not res["sans_trace"] else "à re-cartographier",
              delta_color="inverse")

    if res.get("col_shape"):
        st.caption(f"Colonne tracé : « {res['col_shape']} »"
                   + (f" · Colonne point : « {res['col_point']} »" if res.get("col_point") else ""))

    if not res["polygones"]:
        st.error("Aucun polygone valide trouvé dans ce fichier.", icon=":material/error:")
        return

    if res["sans_trace"]:
        st.warning(
            f"**{len(res['sans_trace'])} enquête(s) sans tracé de parcelle** — "
            "elles ne figureront pas dans le fichier de polygones. Les équipes "
            "de terrain doivent retourner tracer ces parcelles :",
            icon=":material/warning:",
        )
        st.table(pd.DataFrame(res["sans_trace"]))

    if res["anomalies"]:
        with st.expander(f"Avertissements ({len(res['anomalies'])})", icon=":material/error:"):
            for a in res["anomalies"]:
                st.write("• " + a)

    # --- Téléchargements ----------------------------------------------------
    st.subheader(":material/download: Téléchargements")
    base = fichier.name.rsplit(".", 1)[0]
    col_a, col_b = st.columns(2)
    with col_a:
        st.download_button(
            f"Fichier polygones ({len(res['polygones'])}) — à charger dans le système",
            data=en_geojson_bytes(res["polygones"], base + "_polygones"),
            file_name=base + "_POLYGONES.geojson",
            mime="application/geo+json",
            type="primary",
            icon=":material/download:",
            width="stretch",
        )
    with col_b:
        if res["points"]:
            st.download_button(
                f"Fichier points ({len(res['points'])}) — pour vérification / QGIS",
                data=en_geojson_bytes(res["points"], base + "_points"),
                file_name=base + "_POINTS.geojson",
                mime="application/geo+json",
                icon=":material/download:",
                width="stretch",
            )

    # --- Tableau récapitulatif ----------------------------------------------
    if res["tableau"]:
        st.subheader(":material/table_chart: Récapitulatif des parcelles")
        tab = pd.DataFrame(res["tableau"])
        st.dataframe(tab, width="stretch", height=350)
        surfaces = tab["Surface GPS (ha)"].dropna()
        if len(surfaces):
            st.caption(
                f"Surface totale mesurée : **{surfaces.sum():.1f} ha** · "
                f"moyenne {surfaces.mean():.2f} ha · "
                f"min {surfaces.min():.2f} · max {surfaces.max():.2f}"
            )

    # --- Carte --------------------------------------------------------------
    st.subheader(":material/map: Aperçu des parcelles")
    try:
        import pydeck as pdk

        donnees = []
        for f in res["polygones"]:
            ring = [[p[0], p[1]] for p in f["geometry"]["coordinates"][0]]
            props = f.get("properties", {})
            donnees.append({
                "contour": ring,
                "nom": identifiant(props, "?"),
                "village": next((props[c] for c in props
                                 if "village" in str(c).lower()), ""),
            })
        lons = [p[0] for d in donnees for p in d["contour"]]
        lats = [p[1] for d in donnees for p in d["contour"]]
        couche = pdk.Layer(
            "PolygonLayer", data=donnees, get_polygon="contour",
            get_fill_color=[34, 139, 34, 120], get_line_color=[0, 90, 0],
            line_width_min_pixels=1, pickable=True,
        )
        vue = pdk.ViewState(
            latitude=sum(lats) / len(lats), longitude=sum(lons) / len(lons),
            zoom=10,
        )
        st.pydeck_chart(pdk.Deck(
            layers=[couche], initial_view_state=vue,
            map_style="light",
            tooltip={"text": "{nom}\n{village}"},
        ))
    except Exception:
        st.caption("(Aperçu cartographique indisponible)")


if __name__ == "__main__":
    main()
