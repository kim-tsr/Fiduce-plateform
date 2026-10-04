"""Bibliothèque transverse de la plateforme Fiduce.

Volontairement minimale : aucun sous-module n'est importé ici afin qu'un service
ne tire que les dépendances qu'il utilise réellement (les sous-modules db / cache
/ broker / security importent leurs dépendances lourdes en interne).
"""

__version__ = "1.0.0"
