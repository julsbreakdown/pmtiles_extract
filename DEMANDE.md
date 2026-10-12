# Extraction PMTiles Mapterhorn haute résolution (Nexsis)

## Demande

Demandeur : Alexandre Gacon (Camptocamp), projet Nexsis.

Encapsuler les appels à la CLI `pmtiles` sur les données [Mapterhorn](https://mapterhorn.com) pour produire **un seul fichier PMTiles** sur une zone donnée, contenant :

- les niveaux par défaut (z0 à z12, déjà couverts aujourd'hui) ;
- les niveaux plus détaillés (z13 et au-delà), jusqu'à un zoom max choisi par l'utilisateur.

Cas d'usage : aller plus loin que le niveau principal sur des **sous-zones** (pas sur la France entière à haute résolution).

Forme retenue : **une lib Python + un provider Processing QGIS** qui l'appelle. La lib doit rester utilisable hors QGIS : côté Nexsis, elle sera appelée depuis **Airflow**.

Contraintes induites par Airflow :

- paquet installable par pip, sans dépendance QGIS ;
- relançable sans effet de bord (une archive déjà extraite est sautée) ;
- retourne les chemins produits, journalise via `logging` ;
- la lib ne fait que l'extraction ; tout post-traitement (hillshade, publication) vit dans le DAG.

API en deux temps, pour le mapping dynamique de tâches Airflow :

- `plan(area, maxzoom) -> list[Job]` : archives z6 intersectant l'emprise, avec URL et zoom max plafonné par archive ; `Job` sérialisable (XCom) ;
- `extract_one(job, output_dir) -> Path` : un `pmtiles extract`, sauté si la sortie existe.

- `plan_base(bbox, region) -> Job | None` : le job z0..12 sur `planet.pmtiles` ;
- `merge(inputs, output) -> Path` : un `pmtiles merge`, sauté si la sortie existe.

DAG type : `plan` puis `extract_one.expand(job=...)` par zone, puis `merge`. Le provider QGIS et la CLI passent par `extract_base` et `extract_zone`, qui enchaînent ces briques.

Hors périmètre pour l'instant : le DAG Airflow et l'export S3 (outillage existant côté Nexsis). La lib écrit sur disque local et retourne les chemins ; l'API ci-dessus doit simplement rester compatible avec ce DAG futur.

## Contexte données Mapterhorn

- z0 à z12 : archive globale `planet.pmtiles` (355 Go).
- z13+ : archives découpées par tuile z6, `https://download.mapterhorn.com/6-{x}-{y}.pmtiles`. Il faut donc interroger les fichiers correspondant à l'emprise demandée.
- Index officiel : `https://download.mapterhorn.com/download_urls.json` (version, et par archive : `url`, `md5sum`, `size`, bbox `min_lon`/`min_lat`/`max_lon`/`max_lat`, `min_zoom`, `max_zoom`). Utilisé par la [carte de couverture](https://mapterhorn.com/coverage/).
- Le zoom max **varie par archive z6** (selon la résolution source) : 13, 14, 15, 16, 17 ou 18. Sur la France : z17 partout, z18 sur `6-33-21` et `6-33-22` (Alpes). Les archives France font de 50 à 615 Go chacune, d'où l'extraction ciblée.
- Couverture fine par source : tuiles vectorielles `https://single-archive-tiles.mapterhorn.com/coverage.json` (couche `coverage`, champ `source`).

## Existant : `bash_hillshade_geojson.sh`

Script bash qui :

1. prend un `MAX_ZOOM >= 13` en paramètre ;
2. boucle sur des tuiles z6 codées en dur (`x` 31..33, `y` 21..23, soit la France) ;
3. lance `pmtiles extract` sur chaque archive distante avec `--region=decoupe_france.json`, `--download-threads=16`, et saute les fichiers déjà présents ;
4. fusionne les résultats avec `pmtiles merge` en `hillshade_full_<MAX_ZOOM>.pmtiles`.

Points relevés à la lecture :

- `--minzoom=--maxzoom=MAX_ZOOM` : n'extrait **qu'un seul niveau**, pas la plage 13..N ni les niveaux 0..12.
- `BBOX_A_REMPLACER` est vide (la boucle sur les bbox est commentée) : seule `--region` filtre réellement.
- Les tuiles z6 sont codées en dur au lieu d'être déduites de l'emprise.
- `pmtiles merge` existe (go-pmtiles 1.31.2) et n'accepte que des archives **disjointes**.

## Comportement cible

Entrées :

- zones, au choix :
  - polygones : dans QGIS, une couche vecteur de l'arbre des couches, une entité par zone, reprojetée en EPSG:4326 ; en CLI, `--geojson zones.geojson` (propriétés optionnelles `name` et `maxzoom` par entité) ;
  - étendue : en CLI, `--extent min_lon,min_lat,max_lon,max_lat`, une seule zone nommée `extent` ;
- zoom max par zone : un champ de la couche (QGIS) ou la propriété `maxzoom` (CLI) ;
- zoom max par défaut, utilisé pour les zones sans valeur ;
- « même zoom pour toutes les zones » : ignore le champ et applique le zoom par défaut partout ;
- nom de zone : un champ de la couche (QGIS) ou la propriété `name` (CLI), sinon `zone_<n>` ;
- dossier de sortie, nombre de threads de téléchargement.

Sortie :

- **un fichier de base** `france_z0-12_<clé>.pmtiles` : z0..12 extrait de `planet.pmtiles` sur la France (`-5.15,42.33,8.23,51.10`), ou `base_z0-12_<clé>.pmtiles` sur une autre emprise donnée par l'utilisateur ;
- **un fichier par zone** `<nom>_z13-<zoom>_<clé>.pmtiles` : z13..zoom de la zone (plafonné par le `max_zoom` de chaque archive), fusion par `pmtiles merge` des extraits de chaque archive z6 touchée. Les extraits d'une même zone viennent d'archives différentes, donc disjoints.

`<clé>` dépend de la géométrie : une zone modifiée produit un nouveau fichier au lieu de réutiliser l'ancien.

Traitement :

1. reprojeter les zones en EPSG:4326 (côté QGIS) ;
2. base : `pmtiles extract planet.pmtiles` z0..12 sur la France par défaut (`--bbox`), ou sur l'emprise de base choisie ;
3. pour chaque zone : archives z6 dont la bbox intersecte celle de la zone, `pmtiles extract` z13..min(zoom, `max_zoom` de l'archive) avec `--region` = la zone, puis `pmtiles merge` en un fichier ;
4. un fichier final déjà présent est sauté ; les extraits intermédiaires sont supprimés après la fusion ;
5. retourner la liste des fichiers produits.

Une zone avec un zoom < 13 est une erreur : la base couvre déjà 0..12.

## Binaire `pmtiles`

Non embarqué. Chemin lu dans un paramètre QGIS (et `--pmtiles-bin` en CLI), à défaut `pmtiles` dans le PATH. Erreur explicite si introuvable.

## Compatibilité QGIS

QGIS 3.34 LTR et plus, et QGIS 4 (Qt6) : imports via `qgis.PyQt` uniquement, pas d'API Qt5-only, `qgisMaximumVersion=4.99` dans `metadata.txt`.

## Développement et validation

- lib : tests unitaires (`plan` sur l'index réel mis en cache, `extract_one` avec un faux binaire) ;
- plugin : validé dans une session QGIS 4.2 vivante via le serveur MCP QGIS. Plugin lié par symlink dans `~/.local/share/QGIS/QGIS4/profiles/jwe/python/plugins/`, rechargé avec `reload_plugin`, algorithme lancé avec `execute_processing` sur une petite zone (quelques km², zoom 13–14) pour garder des extraits légers.

## Structure proposée

```
plugin_pmtiles/
├── pyproject.toml               # paquet pip mapterhorn-extract (lib seule)
├── mapterhorn_extract/          # lib, stdlib uniquement, sans dépendance QGIS
│   ├── index.py                 # download_urls.json -> Archive
│   ├── area.py                  # --geojson / --extent -> bbox validée EPSG:4326
│   ├── pmtiles_bin.py           # localisation du binaire, commande extract
│   ├── extract.py               # plan(), plan_base(), extract_one(), merge(), Job
│   ├── zones.py                 # Zone, zones_from_geojson, extract_base, extract_zone
│   └── __main__.py              # CLI : --geojson | --extent, --maxzoom, --output-dir
├── mapterhorn_pmtiles/          # plugin QGIS
│   ├── mapterhorn_extract -> ../mapterhorn_extract   # symlink, résolu au zip
│   ├── metadata.txt
│   ├── __init__.py
│   ├── plugin.py                # enregistrement du provider
│   ├── provider.py
│   ├── compat.py                # enums QGIS 3.34 / 4
│   └── algorithm.py             # QgsProcessingAlgorithm mapterhorn:extract
└── tests/
```

Le chargement des résultats comme couches QGIS est reporté : un PMTiles Terrarium s'affiche comme une image RGB, pas comme un MNT.

## Questions ouvertes

- Consommateur Nexsis : fichiers servis tels quels (MapLibre `raster-dem`) ou convertis en hillshade dans le DAG ? Hors périmètre de la lib, mais à clarifier avec Alexandre.
- Volume : prévoir une estimation de taille / nombre de tuiles avant lancement ?
