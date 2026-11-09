"""Loads the YAML configuration that drives the pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mabat.anomalies.rules import Thresholds, load_thresholds
from mabat.ingest.fieldmap import FieldMap, load_fieldmap
from mabat.normalize.classify import Classification, load_classification

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@dataclass(frozen=True)
class Config:
    fieldmap: FieldMap
    classification: Classification
    thresholds: Thresholds


def load_config(config_dir: Path | str = DEFAULT_CONFIG_DIR) -> Config:
    config_dir = Path(config_dir)
    return Config(
        fieldmap=load_fieldmap(config_dir / "fieldmap.yaml"),
        classification=load_classification(config_dir / "classification.yaml"),
        thresholds=load_thresholds(config_dir / "thresholds.yaml"),
    )
