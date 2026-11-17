from __future__ import annotations


class EldaError(Exception):
    default_fr = "Une erreur est survenue."

    def __init__(self, message_fr: str = ""):
        self.message_fr = message_fr or self.default_fr
        super().__init__(self.message_fr)


class NetworkError(EldaError):
    default_fr = "Impossible de joindre le serveur ELDA. Vérifiez votre connexion."


class ServerError(EldaError):
    default_fr = "Le serveur ELDA a rencontré une erreur. Réessayez dans un instant."

    def __init__(self, status: int = 0, message_fr: str = ""):
        self.status = status
        super().__init__(message_fr)


class RequestRefused(EldaError):
    default_fr = "Le serveur ELDA a refusé la demande."

    def __init__(self, status: int = 0, message: str = ""):
        self.status = status
        super().__init__(message)


class AuthError(EldaError):
    default_fr = "Identifiants incorrects."


class SessionLost(EldaError):
    default_fr = "Votre session a expiré. Reconnectez-vous."


class UnsafeUrl(EldaError):
    default_fr = "Adresse du serveur refusée : utilisez une adresse https:// valide, sans identifiants."
