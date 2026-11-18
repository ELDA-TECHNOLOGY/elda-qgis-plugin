"""All French user-facing strings; no Qt import so they stay testable."""
from __future__ import annotations

import html

TITLE = "ELDA"
LOGIN_TITLE = "Connexion à ELDA"
SERVER = "Serveur"
OTHER_SERVER = "Autre adresse…"
OTHER_SERVER_PLACEHOLDER = "https://…"
USERNAME = "Identifiant"
PASSWORD = "Mot de passe"
REMEMBER = "Se souvenir de moi sur ce poste"
CONNECT = "Se connecter"
LOGOUT = "Se déconnecter"
FORGET = "Oublier ce compte"
BUSY = "Connexion en cours…"
WAIT = "Patientez…"
SINGLE_SESSION_WARNING = "Se connecter ici déconnectera, sous 24 h, votre session ELDA du site web ou de la tablette pour ce compte."
CREDENTIALS_NOT_FORGOTTEN = "Les identifiants enregistrés n'ont pas pu être effacés de ce poste."
LOGGED_OUT = "Vous n'êtes pas connecté."
CREDENTIALS_NOT_SAVED = "Les identifiants n'ont pas pu être mémorisés sur ce poste."
UNEXPECTED_ERROR = "Une erreur inattendue est survenue."
ACCOUNT_FORGOTTEN = "Compte oublié sur ce poste."
SERVER_CHANGED = "Le serveur a changé : saisissez à nouveau votre mot de passe."
MISSING_FIELDS = "Saisissez votre identifiant et votre mot de passe."

_RIGHTS = {"vector": "Couches vecteur", "raster": "Rasters"}


def rights_line(kind: str, allowed: bool) -> str:
    return "%s : %s" % (_RIGHTS[kind], "autorisé" if allowed else "non autorisé")


def forget_message(forgotten: bool) -> tuple:
    """(text, is_warning) to show after forgetting an account."""
    if forgotten:
        return ACCOUNT_FORGOTTEN, False
    return CREDENTIALS_NOT_FORGOTTEN, True


def site_label(name: str) -> str:
    return "Site : " + name


def _host(server_url: str) -> str:
    return server_url.split("://", 1)[-1]


def connected_as(username: str, server_url: str) -> str:
    return "Connecté : %s (%s)" % (username, _host(server_url))


def unknown_server(server_url: str) -> str:
    return (
        "« %s » n'est pas un serveur ELDA connu. Vos identifiants lui seront envoyés. Continuer ?" % _host(server_url)
    )


def plain_tooltip(text) -> str:
    """Qt renders tooltips that look like HTML: escape, then declare it rich, so markup shows as text."""
    return "<qt>%s</qt>" % html.escape(text) if text else ""


NOT_LOGGED_IN = "Connectez-vous à ELDA pour publier."
PUBLISH_BUSY = "Une publication est déjà en cours."
TICK_AT_LEAST_ONE = "Cochez au moins une couche."
MAX_LAYERS = "20 couches au maximum par envoi."
NO_VECTOR_RIGHT = "Votre compte n'a pas le droit de publier des couches vecteur sur ce site."
COMING_SOON = "Disponible dans une prochaine version"

_STATUS = {
    "waiting": "En attente",
    "preparing": "Préparation…",
    "processing": "Traitement par ELDA…",
    "published": "Publiée",
    "failed": "Échec",
    "cancelled": "Annulée",
    "timeout": "Traitement trop long",
    "unpublished": "Non publiée",
}


def status_text(code: str, percent) -> str:
    """Display text of a row status code; percent only matters while uploading."""
    if code == "uploading":
        return "Envoi…" if percent is None else "Envoi… %d %%" % percent
    return _STATUS.get(code, "")


def _plural(n: int, one: str, many: str) -> str:
    return "%d %s" % (n, one if n == 1 else many)


def summary_published(n: int) -> str:
    return "Aucune couche publiée" if n == 0 else _plural(n, "couche publiée", "couches publiées")


def summary_failed(n: int) -> str:
    return "%d en échec" % n


def summary_cancelled(n: int) -> str:
    return _plural(n, "annulée", "annulées")


def summary_timeout(n: int) -> str:
    return _plural(n, "traitement trop long", "traitements trop longs")


def summary_unpublished(n: int) -> str:
    return _plural(n, "non publiée", "non publiées")


PUBLISH = "Publier"
WITH_STYLE = "Reprendre le style QGIS"
WITH_STYLE_HINT = "S'applique aux nouvelles couches. Une couche dont le contenu est remplacé garde son style ELDA."
CANCEL = "Annuler"
REFRESH = "Actualiser"
SITE_ROOT = "Racine du site"
UNNAMED_FOLDER = "(sans nom)"
LOADING = "Chargement…"
RETRY_FOLDER = "Rouvrez le dossier pour réessayer."
FOLDER_LABEL = "Dossier :"
VISIBILITY_LABEL = "Visibilité :"
FOLDER_TITLE = "Choisir un dossier ELDA"
VISIBILITY_TITLE = "Visibilité des couches publiées"
WHOLE_SITE = "Tout le site"
RESTRICT = "Restreindre à…"
YES = "Oui"
NO = "Non"


def restrict_label(restricted: bool, chosen: int) -> str:
    """Restricting to nobody still leaves the layer visible to its author: say so."""
    return RESTRICT + " (vous seulement)" if restricted and chosen == 0 else RESTRICT
GROUPS = "Groupes"
USERS = "Utilisateurs"
USERS_REFUSED = "Votre compte ne permet pas de lister les utilisateurs : seuls les groupes sont proposés."
CLOSE_DURING_BATCH = "Une publication est en cours. L'annuler ?"
TASK_LOADING = "ELDA : chargement"
EXPORT_EMPTY = (
    "QGIS n'a pu lire aucune entité de cette couche : son fichier source a peut-être été déplacé, "
    "remplacé ou supprimé. Rien n'a été envoyé à ELDA. Rechargez la couche dans QGIS, puis réessayez."
)
CHECKING_EXISTING = "Vérification des couches déjà présentes dans ELDA…"
_COLUMNS = ("", "Nom dans ELDA", "Type", "Entités", "État")

_KINDS = {"vector": "Vecteur", "raster": "Raster"}


def column_titles() -> list:
    return list(_COLUMNS)


def kind_text(kind: str) -> str:
    return _KINDS.get(kind, "Autre")


def feature_count(count) -> str:
    return "" if count is None else str(count)


def publish_task(layer_name: str) -> str:
    return "ELDA : publication de " + layer_name


def confirm_slow(minutes: int) -> str:
    return "L'envoi devrait durer environ %d minutes, au-delà de la limite d'une heure. Continuer ?" % minutes


REPLACE_CONTENT = "Remplacer le contenu"
CREATE_NEW = "Créer une nouvelle couche"


def _already_there(names) -> str:
    listed = ", ".join("« %s »" % n for n in names)
    return "Une couche du même nom existe déjà dans ELDA, dans ce dossier : %s." % listed


def choose_duplicate(names) -> str:
    return (
        _already_there(names) + "\n\n"
        "Remplacer le contenu efface toutes les entités de la couche ELDA et les remplace par celles de QGIS. "
        "Les modifications faites dans ELDA seront perdues, et ce remplacement ne peut pas être annulé. "
        "Le nom, le dossier, la visibilité et le style de la couche ELDA sont conservés.\n\n"
        "Créer une nouvelle couche ajoute un doublon dans ELDA."
    )


def confirm_duplicate(names, several: bool) -> str:
    why = (
        "Plusieurs couches portent ce nom : le plugin ne peut pas choisir laquelle remplacer."
        if several
        else "La couche existante est en cours de traitement ou en échec : son contenu ne peut pas être remplacé."
    )
    return "%s\n\n%s\n\nPublier quand même crée un doublon dans ELDA. Continuer ?" % (_already_there(names), why)


def visibility_summary(restricted: bool, groups: int, users: int) -> str:
    if not restricted:
        return WHOLE_SITE
    parts = []
    if groups:
        parts.append(_plural(groups, "groupe", "groupes"))
    if users:
        parts.append(_plural(users, "utilisateur", "utilisateurs"))
    return "Restreint : " + (", ".join(parts) if parts else "vous seul")
