"""Texts of the rule messages and the PDF report in English, Dutch and French."""
from typing import Any

LANGUAGES = ('en', 'nl', 'fr')

MESSAGES = {
    'no_route': {
        'en': "No escape route found",
        'nl': "Geen evacuatieweg gevonden",
        'fr': "Aucun chemin d'évacuation trouvé",
    },
    'needs_exits': {
        'en': "Needs {needed} exits (LG 2.2.1), can reach {reached}",
        'nl': "Vereist {needed} uitgangen (LG 2.2.1), bereikt er {reached}",
        'fr': "Exige {needed} sorties (LG 2.2.1), en atteint {reached}",
    },
    'nearest_exit': {
        'en': "Distance to nearest exit ({distance:.1f} m) exceeds maximum ({limit} m)",
        'nl': "Afstand tot dichtstbijzijnde uitgang ({distance:.1f} m) overschrijdt het maximum ({limit} m)",
        'fr': "Distance jusqu'à la sortie la plus proche ({distance:.1f} m) dépasse le maximum ({limit} m)",
    },
    'second_exit': {
        'en': "Distance to second exit ({distance:.1f} m) exceeds maximum ({limit} m)",
        'nl': "Afstand tot tweede uitgang ({distance:.1f} m) overschrijdt het maximum ({limit} m)",
        'fr': "Distance jusqu'à une deuxième sortie ({distance:.1f} m) dépasse le maximum ({limit} m)",
    },
    'second_exit_beyond': {
        'en': "Distance to second exit is more than {beyond:.0f} m (maximum {limit} m)",
        'nl': "Afstand tot tweede uitgang is meer dan {beyond:.0f} m (maximum {limit} m)",
        'fr': "Distance jusqu'à une deuxième sortie de plus de {beyond:.0f} m (maximum {limit} m)",
    },
    'diag_no_exit_on_floor': {
        'en': 'No exit on this floor: no outside door, and no stair to the evacuation level',
        'nl': 'Geen uitgang op deze bouwlaag: geen buitendeur en geen trap naar het evacuatieniveau',
        'fr': "Aucune sortie à ce niveau : ni porte extérieure, ni escalier vers le niveau d'évacuation",
    },
    'diag_narrow': {
        'en': 'Only reachable through a passage narrower than the clear width (bottleneck marked)',
        'nl': 'Enkel bereikbaar via een doorgang smaller dan de vrije breedte (knelpunt aangeduid)',
        'fr': 'Accessible seulement par un passage plus étroit que la largeur libre (goulot indiqué)',
    },
    'diag_walled_off': {
        'en': 'Walled off from every exit on this floor; check the doors and walls',
        'nl': 'Afgesloten van elke uitgang op deze bouwlaag; controleer deuren en wanden',
        'fr': 'Séparé de toutes les sorties de ce niveau ; vérifier portes et murs',
    },
    # report
    'title': {'en': "Escape routes report", 'nl': "Rapport evacuatiewegen", 'fr': "Rapport des chemins d'évacuation"},
    'file': {'en': "File", 'nl': "Bestand", 'fr': "Fichier"},
    'scope': {
        'en': 'Checked against KB 7 July 1994, annex 2/1 (low buildings): number of exits (LG 2.2.1), distance to the nearest and a second exit (LG 4.4.1.1), and what counts as an exit (LG 4.4.1.2).',
        'nl': 'Getoetst aan KB 7 juli 1994, bijlage 2/1 (lage gebouwen): aantal uitgangen (LG 2.2.1), afstand tot de dichtstbijzijnde en een tweede uitgang (LG 4.4.1.1) en wat als uitgang telt (LG 4.4.1.2).',
        'fr': "Vérifié selon l'AR du 7 juillet 1994, annexe 2/1 (bâtiments bas) : nombre de sorties (LG 2.2.1), distance jusqu'à la sortie la plus proche et une deuxième sortie (LG 4.4.1.1), et ce qui compte comme sortie (LG 4.4.1.2).",
    },
    'compartments': {'en': "Compartments", 'nl': "Compartimenten", 'fr': "Compartiments"},
    'occupancy': {'en': "occupancy", 'nl': "bezetting", 'fr': "occupation"},
    'persons': {'en': "persons", 'nl': "personen", 'fr': "personnes"},
    'not_given': {'en': "not given", 'nl': "niet opgegeven", 'fr': "non indiquée"},
    'exits_required': {'en': "exits required", 'nl': "vereiste uitgangen", 'fr': "sorties requises"},
    'violations': {'en': "Spaces with violations", 'nl': "Ruimten met overtredingen", 'fr': "Locaux avec non-conformités"},
    'none_found': {'en': "No violations found.", 'nl': "Geen overtredingen gevonden.", 'fr': "Aucune non-conformité."},
    'overview': {'en': "Overview of all spaces", 'nl': "Overzicht van alle ruimten", 'fr': "Aperçu de tous les locaux"},
    'floor': {'en': "Floor", 'nl': "Bouwlaag", 'fr': "Niveau"},
    'no_routes_floor': {'en': "No spaces on this floor.", 'nl': "Geen ruimten op deze bouwlaag.", 'fr': "Aucun local à ce niveau."},
    'col_space': {'en': "Space", 'nl': "Ruimte", 'fr': "Local"},
    'col_use': {'en': "Use", 'nl': "Gebruik", 'fr': "Usage"},
    'col_exit_m': {'en': "To exit (m)", 'nl': "Tot uitgang (m)", 'fr': "Vers sortie (m)"},
    'col_exit': {'en': "Exit", 'nl': "Uitgang", 'fr': "Sortie"},
    'col_second': {'en': "2nd exit (m)", 'nl': "2e uitgang (m)", 'fr': "2e sortie (m)"},
    'col_issues': {'en': "Issues", 'nl': "Opmerkingen", 'fr': "Remarques"},
    'day': {'en': "day", 'nl': "dag", 'fr': "jour"},
    'night': {'en': "night", 'nl': "nacht", 'fr': "nuit"},
    'unknown': {'en': "day/night", 'nl': "dag/nacht", 'fr': "jour/nuit"},
    'daytime': {'en': "Day occupancy", 'nl': "Dagbezetting", 'fr': "Occupation de jour"},
    'nighttime': {'en': "Night occupancy", 'nl': "Nachtbezetting", 'fr': "Occupation de nuit"},
    'general': {'en': "General", 'nl': "Algemeen", 'fr': "Général"},
    'not_checked': {'en': "Not checked", 'nl': "Niet gecontroleerd", 'fr': "Non vérifié"},
    'outside': {'en': "outside", 'nl': "buiten", 'fr': "extérieur"},
    'stairwell': {'en': "stairwell", 'nl': "trappenhuis", 'fr': "cage d'escalier"},
    'stairwell door': {'en': "stairwell door", 'nl': "deur trappenhuis", 'fr': "porte de cage d'escalier"},
    'evacuation route': {'en': "evacuation route", 'nl': "evacuatieweg", 'fr': "chemin d'évacuation"},
    'exit': {'en': "exit", 'nl': "uitgang", 'fr': "sortie"},
}

NOT_CHECKED = {
    'en': [
        "Distance to the evacuation route connecting the exits, 30 m day / 20 m night (LG 4.4.1.1): the grid does not show evacuation routes",
        "Dead ends of at most 15 m (LG 4.4.1.1)",
        "Width per occupant, 1 cm per person in 0.60 m units (LG 4.4.1.1, annex 1, 5.6.7); only the 0.80 m minimum is checked",
        "External stairs as exits, fire resistance of protected routes, enclosed stairwells (LG 4.4.1.2, 4.2)",
        "Exits in opposite zones of the compartment (LG 2.2.2)",
        "Parkings (LG 5.2) are not left out",
    ],
    'nl': [
        "Afstand tot de evacuatieweg die de uitgangen verbindt, 30 m dag / 20 m nacht (LG 4.4.1.1): het raster toont geen evacuatiewegen",
        "Doodlopende evacuatiewegen van ten hoogste 15 m (LG 4.4.1.1)",
        "Breedte volgens de bezetting, 1 cm per persoon in eenheden van 0,60 m (LG 4.4.1.1, bijlage 1, 5.6.7); enkel het minimum van 0,80 m wordt gecontroleerd",
        "Buitentrappen als uitgang, brandweerstand van beschermde evacuatiewegen, omsloten trappenhuizen (LG 4.4.1.2, 4.2)",
        "Uitgangen in tegenovergestelde zones van het compartiment (LG 2.2.2)",
        "Parkings (LG 5.2) worden niet uitgesloten",
    ],
    'fr': [
        "Distance jusqu'au chemin d'évacuation reliant les sorties, 30 m jour / 20 m nuit (LG 4.4.1.1) : la grille ne montre pas les chemins d'évacuation",
        "Culs-de-sac de 15 m au plus (LG 4.4.1.1)",
        "Largeur selon l'occupation, 1 cm par personne par unités de 0,60 m (LG 4.4.1.1, annexe 1, 5.6.7) ; seul le minimum de 0,80 m est vérifié",
        "Escaliers extérieurs comme sorties, résistance au feu des chemins protégés, cages d'escalier fermées (LG 4.4.1.2, 4.2)",
        "Sorties dans des zones opposées du compartiment (LG 2.2.2)",
        "Les parkings (LG 5.2) ne sont pas exclus",
    ],
}


def t(lang: str, key: str, **values: Any) -> str:
    texts = MESSAGES.get(key)
    if texts is None:
        return key
    text = texts.get(lang if lang in LANGUAGES else 'en', texts['en'])
    return text.format(**values) if values else text


def not_checked(lang: str):
    return NOT_CHECKED.get(lang if lang in LANGUAGES else 'en')
