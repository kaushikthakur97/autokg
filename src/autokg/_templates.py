from __future__ import annotations

from typing import Optional

import polars as pl

from ._types import (
    COLUMN_ROLE_FOREIGN_KEY,
    COLUMN_ROLE_LIST,
    COLUMN_ROLE_PRIMARY_KEY,
    detect_column_role,
    detect_list_columns,
    detect_primary_key,
    infer_xsd_type,
    resolve_auto_map,
    resolve_prefix,
    sanitize_name,
)


class TemplateGenerator:
    def __init__(
        self,
        namespace: str,
        entity_type: str,
        iri_column: Optional[str] = None,
        property_map: Optional[dict[str, str]] = None,
        fk_mapping: Optional[dict[str, str]] = None,
        use_maplib: bool = True,
    ):
        self.namespace = namespace.rstrip("/#")
        self.entity_type = entity_type
        self.iri_column = iri_column
        self.property_map = property_map or {}
        self.fk_mapping = fk_mapping or {}
        self.use_maplib = use_maplib

    def analyze(self, df: pl.DataFrame) -> dict:
        pk = self.iri_column or detect_primary_key(df)
        cols = {}
        for col in df.columns:
            role = detect_column_role(df, col, pk)
            xsd_type = infer_xsd_type(df[col].dtype)
            auto_prop = resolve_auto_map(col)
            cols[col] = {
                "role": role,
                "dtype": str(df[col].dtype),
                "xsd_type": xsd_type,
                "auto_property": auto_prop,
                "is_nullable": df[col].null_count() > 0,
                "n_unique": df[col].n_unique(),
            }
        list_cols = detect_list_columns(df)
        for col in list_cols:
            cols[col]["role"] = COLUMN_ROLE_LIST

        return {
            "entity_type": self.entity_type,
            "primary_key": pk,
            "columns": cols,
            "total_rows": df.height,
            "total_columns": len(df.columns),
        }

    def generate(self, df: pl.DataFrame) -> "GeneratedTemplate":
        if self.use_maplib:
            return self._generate_maplib(df)
        return self._generate_manual(df)

    def _generate_maplib(self, df: pl.DataFrame) -> "GeneratedTemplate":
        try:
            from maplib import (
                Model,
                Prefix,
                Template,
                Argument,
                Parameter,
                Variable,
                RDFType,
                Triple,
                a,
            )
        except ImportError:
            raise ImportError("maplib required for template generation. Install with: pip install maplib")

        pk = self.iri_column or detect_primary_key(df)
        if not pk:
            pk = "__row_id__"
            df = df.with_row_index(pk)

        ns = Prefix(self.namespace + "/" if not self.namespace.endswith("/") else self.namespace)
        entity_iri = ns.suf(f"{self.entity_type}")

        params: list[Parameter] = []
        instances: list[Triple] = []
        variables: dict[str, Variable] = {}
        exclusions: set[str] = set()

        iri_var = Variable("_iri")
        variables["_iri"] = iri_var

        params.append(Parameter(variable=iri_var, rdf_type=RDFType.IRI()))
        instances.append(Triple(iri_var, a, entity_iri))

        for col in df.columns:
            if col == pk:
                continue
            if col in exclusions:
                continue
            if col.startswith("_iris_kg_"):
                continue

            role = detect_column_role(df, col, pk)
            prop = self.property_map.get(col) or resolve_auto_map(col)
            if not prop:
                safe = sanitize_name(col)
                prop = f"ex:{safe}"

            resolved_prop = resolve_prefix(prop)
            if not resolved_prop.startswith("http"):
                resolved_prop = ns.suf(resolved_prop.split(":", 1)[-1] if ":" in resolved_prop else resolved_prop)

            col_var = Variable(f"_col_{col}")
            variables[col] = col_var

            if role == COLUMN_ROLE_FOREIGN_KEY or col in self.fk_mapping:
                target_entity = self.fk_mapping.get(col, col.replace("_id", "").title().replace(" ", ""))
                fk_prefix = self.namespace + "/" if "/" not in self.namespace[-3:] else self.namespace
                fk_var = Variable(f"_fk_{col}")

                params.append(Parameter(variable=fk_var, rdf_type=RDFType.IRI()))
                instances.append(Triple(iri_var, resolved_prop, fk_var))

            elif role == COLUMN_ROLE_LIST:
                params.append(Parameter(variable=col_var, rdf_type=RDFType.Nested(RDFType.IRI())))
                instances.append(
                    Triple(iri_var, resolved_prop, Argument(term=col_var, list_expand=True), list_expander="cross")
                )

            else:
                xsd_type = infer_xsd_type(df[col].dtype)
                params.append(Parameter(variable=col_var, rdf_type=RDFType.Literal(datatype=xsd_type)))
                instances.append(Triple(iri_var, resolved_prop, col_var))

        template = Template(
            iri=ns.suf(f"{self.entity_type}Template"),
            parameters=params,
            instances=instances,
        )

        return GeneratedTemplate(template=template, model=None, pk_column=pk, var_map={v.name: v for v in variables.values()})

    def _generate_manual(self, df: pl.DataFrame) -> "GeneratedTemplate":
        pk = self.iri_column or detect_primary_key(df) or "__row_id__"
        return GeneratedTemplate(
            template=None, model=None, pk_column=pk,
            var_map={}, _generator=self, _df_reference=df.clone()
        )

    def generate_triples_manual(self, df: pl.DataFrame, iri_col: str = "_iris_kg_iri") -> list[dict[str, str]]:
        triples: list[dict[str, str]] = []
        pk = self.iri_column or detect_primary_key(df)

        for row in df.iter_rows(named=True):
            subj = row[iri_col] if iri_col in row else row.get(pk, "")

            for col in df.columns:
                if col == pk or col == iri_col or col.startswith("_iris_kg_"):
                    continue
                val = row[col]
                if val is None:
                    continue

                role = detect_column_role(df, col, pk)
                prop = self.property_map.get(col) or resolve_auto_map(col)
                if not prop:
                    prop = f"{self.namespace}/{sanitize_name(col)}"

                resolved = resolve_prefix(prop)

                if role == COLUMN_ROLE_FOREIGN_KEY or col in self.fk_mapping:
                    target = self.fk_mapping.get(col, col.replace("_id", "").title().replace(" ", ""))
                    obj = f"{self.namespace}/{target}/{val}"
                    triples.append({"subject": subj, "predicate": resolved, "object": obj, "is_iri": True})
                elif role == COLUMN_ROLE_LIST and isinstance(val, list):
                    for item in val:
                        triples.append({"subject": subj, "predicate": resolved, "object": str(item), "is_iri": True})
                else:
                    triples.append({
                        "subject": subj, "predicate": resolved, "object": str(val), "is_iri": False,
                        "datatype": infer_xsd_type(df[col].dtype),
                    })

        return triples


class GeneratedTemplate:
    def __init__(self, template=None, model=None, pk_column=None, var_map=None,
                 _generator=None, _df_reference=None):
        self.template = template
        self.model = model
        self.pk_column = pk_column
        self.var_map = var_map or {}
        self._generator = _generator
        self._df_reference = _df_reference

    def generate_triples_manual(self, df=None) -> list[dict[str, str]]:
        if self._generator is not None:
            resolved_df = df if df is not None else self._df_reference
            return self._generator.generate_triples_manual(resolved_df)
        return []
