from __future__ import annotations

import re
from typing import Any, Optional, Tuple

import polars as pl

XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
SCHEMA = "https://schema.org/"
DCAT = "http://www.w3.org/ns/dcat#"
DCTERMS = "http://purl.org/dc/terms/"
PROV = "http://www.w3.org/ns/prov#"
FOAF = "http://xmlns.com/foaf/0.1/"
SKOS = "http://www.w3.org/2004/02/skos/core#"

XSD_TYPE_MAP: dict[pl.DataType, str] = {
    pl.Int8: f"{XSD}byte",
    pl.Int16: f"{XSD}short",
    pl.Int32: f"{XSD}int",
    pl.Int64: f"{XSD}long",
    pl.UInt8: f"{XSD}unsignedByte",
    pl.UInt16: f"{XSD}unsignedShort",
    pl.UInt32: f"{XSD}unsignedInt",
    pl.UInt64: f"{XSD}unsignedLong",
    pl.Float32: f"{XSD}float",
    pl.Float64: f"{XSD}double",
    pl.Boolean: f"{XSD}boolean",
    pl.Utf8: f"{XSD}string",
    pl.String: f"{XSD}string",
    pl.Date: f"{XSD}date",
    pl.Datetime: f"{XSD}dateTime",
    pl.Time: f"{XSD}time",
    pl.Duration: f"{XSD}duration",
    pl.Binary: f"{XSD}hexBinary",
    pl.Decimal: f"{XSD}decimal",
}

COLUMN_ROLE_PRIMARY_KEY = "primary_key"
COLUMN_ROLE_FOREIGN_KEY = "foreign_key"
COLUMN_ROLE_LITERAL = "literal"
COLUMN_ROLE_TEMPORAL = "temporal"
COLUMN_ROLE_LIST = "list"
COLUMN_ROLE_UNKNOWN = "unknown"

PK_NAME_PATTERNS = [
    re.compile(r"^id$", re.IGNORECASE),
    re.compile(r"^[a-z]+_id$", re.IGNORECASE),
    re.compile(r"^uuid$", re.IGNORECASE),
    re.compile(r"^pk$", re.IGNORECASE),
    re.compile(r"^key$", re.IGNORECASE),
]

FK_NAME_PATTERNS = [
    re.compile(r"^([a-z]+)_id$", re.IGNORECASE),
    re.compile(r"^fk_([a-z]+)$", re.IGNORECASE),
    re.compile(r"^([a-z]+)_ref$", re.IGNORECASE),
]

TEMPORAL_NAME_PATTERNS = [
    re.compile(r"^(created|updated|modified|deleted|expired|start|end|began|closed)", re.IGNORECASE),
    re.compile(r".*_(at|on|date|time)$", re.IGNORECASE),
    re.compile(r"^(date|time)", re.IGNORECASE),
]

NUMERIC_NAME_PATTERNS = [
    re.compile(r"^(amount|price|cost|value|total|sum|fee|rate|tax|discount|quantity|qty|count|num|score|rank|percent|ratio)", re.IGNORECASE),
    re.compile(r".*_(amount|price|cost|value|total|fee|rate)", re.IGNORECASE),
]

BOOLEAN_NAME_PATTERNS = [
    re.compile(r"^(is_|has_|should_|can_|was_)", re.IGNORECASE),
    re.compile(r"^(active|enabled|approved|verified|deleted|archived)$", re.IGNORECASE),
    re.compile(r".*_flag$", re.IGNORECASE),
]

AUTO_MAP_VOCABULARY: dict[str, list[str]] = {
    "name": ["schema:name", "foaf:name", "dcterms:title", "rdfs:label"],
    "first_name": ["schema:givenName", "foaf:firstName"],
    "last_name": ["schema:familyName", "foaf:lastName"],
    "full_name": ["schema:name", "foaf:name"],
    "email": ["schema:email", "foaf:mbox"],
    "phone": ["schema:telephone", "foaf:phone"],
    "address": ["schema:address", "vcard:hasAddress"],
    "city": ["schema:addressLocality"],
    "country": ["schema:addressCountry"],
    "postal_code": ["schema:postalCode"],
    "description": ["schema:description", "dcterms:description", "rdfs:comment"],
    "bio": ["schema:description", "foaf:description"],
    "birth_date": ["schema:birthDate"],
    "death_date": ["schema:deathDate"],
    "gender": ["schema:gender"],
    "image": ["schema:image", "foaf:depiction"],
    "photo": ["schema:image", "foaf:img"],
    "logo": ["schema:logo"],
    "url": ["schema:url", "foaf:homepage"],
    "website": ["schema:url"],
    "homepage": ["foaf:homepage"],
    "username": ["schema:alternateName"],
    "identifier": ["schema:identifier", "dcterms:identifier"],
    "title": ["schema:title", "dcterms:title"],
    "created_at": ["schema:dateCreated", "dcterms:created", "prov:generatedAtTime"],
    "updated_at": ["schema:dateModified", "dcterms:modified"],
    "modified_at": ["schema:dateModified", "dcterms:modified"],
    "published_at": ["schema:datePublished"],
    "price": ["schema:price"],
    "amount": ["schema:amount"],
    "currency": ["schema:priceCurrency"],
    "status": ["schema:eventStatus"],
    "type": ["rdf:type", "dcterms:type"],
    "category": ["schema:category", "dcterms:subject"],
    "tag": ["schema:keywords"],
    "keyword": ["schema:keywords"],
    "language": ["schema:inLanguage"],
    "rating": ["schema:ratingValue"],
    "review": ["schema:review"],
    "comment": ["schema:comment", "rdfs:comment"],
    "latitude": ["schema:latitude", "geo:lat"],
    "longitude": ["schema:longitude", "geo:long"],
    "start_date": ["schema:startDate"],
    "end_date": ["schema:endDate"],
    "duration": ["schema:duration"],
    "color": ["schema:color"],
    "size": ["schema:size"],
    "weight": ["schema:weight"],
    "manufacturer": ["schema:manufacturer"],
    "brand": ["schema:brand"],
    "model": ["schema:model"],
    "sku": ["schema:sku"],
    "isbn": ["schema:isbn"],
    "author": ["schema:author"],
    "publisher": ["schema:publisher", "dcterms:publisher"],
    "location": ["schema:location"],
    "role": ["schema:roleName"],
    "department": ["schema:department"],
    "organization": ["schema:memberOf"],
    "company": ["schema:worksFor"],
    "industry": ["schema:industry"],
    "employee_count": ["schema:numberOfEmployees"],
    "founding_date": ["schema:foundingDate"],
}

PREFIX_MAP: dict[str, str] = {
    "schema": SCHEMA,
    "dcat": DCAT,
    "dcterms": DCTERMS,
    "dct": DCTERMS,
    "prov": PROV,
    "foaf": FOAF,
    "skos": SKOS,
    "rdf": RDF,
    "rdfs": RDFS,
    "owl": OWL,
    "xsd": XSD,
}


def resolve_prefix(prefixed: str) -> str:
    if ":" in prefixed:
        prefix, local = prefixed.split(":", 1)
        if prefix.lower() in PREFIX_MAP:
            return f"{PREFIX_MAP[prefix.lower()]}{local}"
    return prefixed


def resolve_auto_map(column_name: str) -> Optional[str]:
    key = column_name.lower().replace(" ", "_").replace("-", "_")
    if key in AUTO_MAP_VOCABULARY:
        return AUTO_MAP_VOCABULARY[key][0]
    return None


def infer_xsd_type(dtype: pl.DataType) -> str:
    if dtype in XSD_TYPE_MAP:
        return XSD_TYPE_MAP[dtype]
    if isinstance(dtype, pl.List):
        inner = infer_xsd_type(dtype.inner)
        return inner
    return f"{XSD}string"


def detect_column_role(df: pl.DataFrame, col: str, pk_candidate: Optional[str] = None) -> str:
    dtype = df[col].dtype

    if pk_candidate and col == pk_candidate:
        return COLUMN_ROLE_PRIMARY_KEY

    for pattern in PK_NAME_PATTERNS:
        if pattern.fullmatch(col):
            return COLUMN_ROLE_PRIMARY_KEY

    for pattern in FK_NAME_PATTERNS:
        m = pattern.fullmatch(col)
        if m:
            return COLUMN_ROLE_FOREIGN_KEY

    if isinstance(dtype, pl.List):
        return COLUMN_ROLE_LIST

    for pattern in TEMPORAL_NAME_PATTERNS:
        if pattern.search(col):
            if dtype in (pl.Date, pl.Datetime, pl.Time):
                return COLUMN_ROLE_TEMPORAL

    return COLUMN_ROLE_LITERAL


def detect_primary_key(df: pl.DataFrame) -> Optional[str]:
    for col in df.columns:
        for pattern in PK_NAME_PATTERNS:
            if pattern.fullmatch(col):
                null_count = df[col].null_count()
                unique_count = df[col].n_unique()
                total = df.height
                if null_count == 0 and unique_count == total:
                    return col
    return None


def detect_foreign_keys(
    df: pl.DataFrame,
    all_dfs: dict[str, pl.DataFrame],
    pk_col: Optional[str] = None,
) -> list[Tuple[str, str, str]]:
    fks: list[Tuple[str, str, str]] = []
    for col in df.columns:
        if pk_col and col == pk_col:
            continue
        m = None
        for pattern in FK_NAME_PATTERNS:
            m = pattern.fullmatch(col)
            if m:
                break
        if not m:
            continue
        fk_entity_hint = m.group(1)
        for other_name, other_df in all_dfs.items():
            other_lower = other_name.lower()
            if fk_entity_hint.lower() in other_lower:
                other_pk = detect_primary_key(other_df)
                if other_pk:
                    fks.append((col, other_name, other_pk))
                    break
    return fks


def detect_list_columns(df: pl.DataFrame) -> list[str]:
    return [col for col in df.columns if isinstance(df[col].dtype, pl.List)]


def detect_temporal_columns(df: pl.DataFrame) -> list[str]:
    temporal: list[str] = []
    for col in df.columns:
        for pattern in TEMPORAL_NAME_PATTERNS:
            if pattern.search(col):
                temporal.append(col)
                break
    return temporal


def sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if cleaned and cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned.lower() or "entity"


def entity_name_from_column(col: str) -> str:
    m = None
    for pattern in FK_NAME_PATTERNS:
        m = pattern.fullmatch(col)
        if m:
            break
    if m:
        return m.group(1).replace("_", " ").title().replace(" ", "")
    return col.replace("_", " ").title().replace(" ", "")
