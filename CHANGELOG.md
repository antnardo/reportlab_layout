# Journal des modifications

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le
versionnage [SemVer](https://semver.org/lang/fr/).

## [1.0.0] — 2026-08-25

Première version publiable. Le paquet `pdf_maker`, jusqu'ici module local, est
découpé, corrigé et renommé `reportlab_layout`. L'API passe en `snake_case` :
c'est une rupture assumée, la table de correspondance complète est dans
[`docs/DOC.md`](docs/DOC.md#migration-depuis-pdf_maker).

### Corrigé

- **Centrage vertical du texte.** L'ancrage se calculait par
  `y - hauteur/2` avec `hauteur = ascendante - descendante`. La descendante
  étant négative, le texte descendait de `|descendante|` de trop, soit environ
  20 % du corps. Le décalage correct est `(ascendante + descendante)/2`.
- **Métriques ignorant l'échelle de tracé.** `drawStringCenterHV` et
  `drawStringLeftCenterV` lisaient la hauteur au corps nominal du style, tandis
  que le texte était dessiné à `fontSize × size` ; `drawStringCenterH` mesurait
  de même la largeur au corps nominal. À `size=0.5`, le centrage était faux d'un
  facteur deux, horizontalement comme verticalement. `TextMetrics` porte
  désormais l'échelle et toutes les métriques en tiennent compte.
- **`before` interprété dans deux unités.** Il était converti en `unit` pour
  positionner l'élément, mais ajouté en points au curseur, décalant tout ce qui
  suivait.
- **`valign="top"` de `drawParagraph`.** La hauteur, en points, était ajoutée à
  une ordonnée exprimée en `unit`. Remplacé par `valign` sur `draw()`, appliqué
  en mode absolu.
- **`addstyle` de `drawTable`.** `TableStyle.add(liste)` empilait la liste comme
  une commande unique, ce qui faisait échouer le rendu du tableau
  (`ValueError: not enough values to unpack`). Les commandes supplémentaires
  passent maintenant par `style=`.
- **`frameParagraph` levait `TypeError`.** Il transmettait `fontsize=` à
  `getParagraph`, qui n'acceptait pas ce paramètre.
- **`get_image` sans largeur levait `TypeError`.** Les paramètres `hauteur` et
  `scale` étaient déclarés mais ignorés. `ImageSpec.scaled` les gère et refuse
  explicitement une demande sans contrainte.
- **`drawParagraph` rendait `(paragraphe, boîte)`**, incohérent avec les autres
  méthodes de tracé, ce qui cassait les appels déballant quatre valeurs. Toutes
  les méthodes rendent désormais une `Box`.
- **`NumberedCanvas` perdait la dernière page** quand il servait de canvas
  autonome, sans `DocTemplate`.
- **États de canvas qui fuyaient.** Couleurs, épaisseur de trait et rotation
  n'étaient pas restaurées après un tracé et contaminaient les suivants.
- **Collision de styles.** La feuille `styles` était un objet de module partagé :
  deux modules définissant le même nom de style levaient `KeyError` à l'import.
- **Impressions sur la sortie standard.** `newFrame` et `drawFrame` écrivaient
  systématiquement sur `stdout` ; le paquet passe par `logging`.

### Ajouté

- `Box`, quadruplet nommé rendu par tous les tracés.
- `TextMetrics`, métriques d'un style à une échelle donnée, avec les ancrages.
- `PageGeometry` et `Cursor`, seuls dépositaires des conversions de repères.
- `draw_string`, méthode unique remplaçant les quatre variantes de tracé de
  chaîne, avec `halign`, `valign`, `angle`, `dx`, `dy`.
- Ancrage `valign="cap"`, centrage sur la boîte de capitale : sur une étiquette
  courte, l'encre tombe au milieu de sa case à moins de 0,02 pt, et une rangée
  d'étiquettes partage la même ligne de base quels que soient leurs jambages.
  `TextMetrics.cap_height` s'appuie sur `STANDARD_CAP_HEIGHTS`, table reprise
  des fichiers AFM d'Adobe, que reportlab n'expose pas ;
  `scripts/cap_height_probe.py` la revérifie par rastérisation.
- `ImageSpec`, remplaçant le dictionnaire à clés françaises.
- `make_stylesheet()` et `add_style()`, pour des feuilles de styles isolées.
- Gestionnaire de contexte : la sortie n'est écrite que si le bloc réussit.
- `cursor_y`, `cursor_point`, `remaining_height`, `Cursor.fits`.
- Prise en charge des noms de format (`"A4"`, `"letter"`) et des couleurs en
  hexadécimal ou en nom CSS.
- Annotations de types sur toute l'API publique, avec `py.typed`.
- 124 tests, exécutés sur Python 3.11 à 3.14 et reportlab 4.x et 5.x.
