from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any, Optional, Union

import polars as pl

_logger = logging.getLogger(__name__)

PII_TYPES: dict[str, str] = {
    "email": "EMAIL_ADDRESS",
    "phone": "PHONE_NUMBER",
    "ssn": "US_SSN",
    "credit_card": "CREDIT_CARD",
    "name": "PERSON",
    "first_name": "PERSON",
    "last_name": "PERSON",
    "full_name": "PERSON",
    "dob": "DATE_TIME",
    "birth_date": "DATE_TIME",
    "ip": "IP_ADDRESS",
    "address": "LOCATION",
    "street": "LOCATION",
    "city": "LOCATION",
    "zip": "LOCATION",
    "postal_code": "LOCATION",
    "passport": "US_PASSPORT",
    "driver_license": "US_DRIVER_LICENSE",
    "bank_account": "IBAN_CODE",
    "nationality": "NRP",
    "gender": "NRP",
    "religion": "NRP",
}

HASH_STRATEGY = "hash"
REDACT_STRATEGY = "redact"
TOKENIZE_STRATEGY = "tokenize"
PSEUDONYMIZE_STRATEGY = "pseudonymize"


class PIIPolicy:
    def __init__(
        self,
        columns: Optional[list[str]] = None,
        strategy: str = "hash",
        detection: str = "explicit",
        salt: str = "autokg-pii-salt",
    ):
        self.columns = columns or []
        self.strategy = strategy
        self.detection = detection
        self.salt = salt
        self._detected_columns: dict[str, str] = {}
        self._masking_log: list[dict] = []

    def detect(self, df: pl.DataFrame, sample_size: int = 100) -> dict[str, str]:
        detected: dict[str, str] = {}
        sample = df.head(sample_size) if df.height > sample_size else df

        if self.detection == "auto":
            try:
                from presidio_analyzer import AnalyzerEngine
                analyzer = AnalyzerEngine()
                for col in df.columns:
                    dtype_obj = df[col].dtype
                    if not isinstance(dtype_obj, (pl.Utf8, pl.String)):
                        continue
                    values = sample[col].drop_nulls().to_list()
                    if not values:
                        continue
                    text = " | ".join(str(v) for v in values[:50] if v)
                    results = analyzer.analyze(text=text, language="en")
                    if results:
                        entity_type = results[0].entity_type
                        detected[col] = entity_type
            except ImportError:
                _logger.info("presidio-analyzer not installed. Using column-name matching only.")
            except Exception as e:
                _logger.warning("PII auto-detection failed: %s. Falling back to column-name matching.", e)

        for col in df.columns:
            if col in detected or col in self.columns:
                continue
            col_lower = col.lower().replace("_", "").replace("-", "")
            for key, pii_type in PII_TYPES.items():
                if key.lower() in col_lower:
                    detected[col] = pii_type
                    break

        self._detected_columns = detected
        return dict(detected)

    def apply(self, df: pl.DataFrame) -> pl.DataFrame:
        all_columns = set(self.columns) | set(self._detected_columns.keys())
        if not all_columns:
            self.detect(df)
            all_columns = set(self.columns) | set(self._detected_columns.keys())

        masked_df = df.clone()
        for col in all_columns:
            if col not in df.columns:
                continue
            pii_type = self._detected_columns.get(col, "UNKNOWN")
            mask_fn = self._get_mask_function()

            masked_df = masked_df.with_columns(
                pl.when(pl.col(col).is_not_null())
                .then(pl.col(col).cast(pl.Utf8).map_elements(mask_fn, return_dtype=pl.Utf8))
                .otherwise(None)
                .alias(col)
            )

            self._masking_log.append({
                "column": col,
                "pii_type": pii_type,
                "strategy": self.strategy,
                "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            })

        return masked_df

    def _get_mask_function(self):
        if self.strategy == HASH_STRATEGY:
            salt = self.salt
            def _hash(val):
                return hashlib.sha256(f"{salt}:{val}".encode()).hexdigest()[:32]
            return _hash
        elif self.strategy == REDACT_STRATEGY:
            return lambda v: "[REDACTED]"
        elif self.strategy == TOKENIZE_STRATEGY:
            _token_map: dict[str, str] = {}
            def _tokenize(val: str) -> str:
                if val not in _token_map:
                    _token_map[val] = f"TOK-{uuid.uuid4().hex[:12]}"
                return _token_map[val]
            return _tokenize
        elif self.strategy == PSEUDONYMIZE_STRATEGY:
            _pseudo_map: dict[str, str] = {}
            def _pseudonymize(val: str) -> str:
                if val not in _pseudo_map:
                    if "@" in val:
                        _pseudo_map[val] = f"user{hashlib.md5(val.encode()).hexdigest()[:6]}@example.com"
                    elif val.replace("+", "").replace("-", "").isdigit():
                        _pseudo_map[val] = f"+X-XXX-{hashlib.md5(val.encode()).hexdigest()[:4]}"
                    else:
                        _pseudo_map[val] = f"[MASKED-{hashlib.md5(val.encode()).hexdigest()[:8]}]"
                return _pseudo_map[val]
            return _pseudonymize
        return lambda v: v

    @property
    def masking_log(self) -> list[dict]:
        return list(self._masking_log)

    @property
    def masked_columns(self) -> list[str]:
        return sorted(set(self.columns) | set(self._detected_columns.keys()))

    def summary(self) -> dict:
        return {
            "strategy": self.strategy,
            "detection_mode": self.detection,
            "explicit_columns": self.columns,
            "detected_columns": self._detected_columns,
            "total_masked": len(self._masking_log),
            "masking_log": self._masking_log,
        }
