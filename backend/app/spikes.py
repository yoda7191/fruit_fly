"""Spike recordings: local disk (default) or S3-compatible object storage.

Local: one folder per experiment with two .npy files. They can be memory-mapped,
so reading a one-second window from hundreds of thousands of spikes touches only
that window.

S3 (FRUIT_FLY_SPIKE_STORE=s3; AWS S3 or MinIO): objects can't be memory-mapped,
and downloading a whole recording to show one second would be slow, so each
recording is split into time chunks (one second by default) plus a meta.json
listing them. A window downloads only the chunks it overlaps. meta.json is
written last, so a reader never sees a half-written recording. Both stores have
the same interface; the job service and API don't know which one they use.
"""

from __future__ import annotations

import io
import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

_SAFE_ID = re.compile(r"^[0-9a-f]{32}$")


def _check_id(experiment_id: str) -> str:
    if not _SAFE_ID.match(experiment_id):              # never build paths or keys from arbitrary text
        raise ValueError(f"invalid experiment id {experiment_id!r}")
    return experiment_id


def _select(n: np.ndarray, t: np.ndarray, t0: float, t1: float, neuron_mask: np.ndarray | None,
            max_spikes: int) -> tuple[np.ndarray, np.ndarray, bool]:
    """Spikes in [t0, t1) of time-sorted arrays, optionally masked, at most max_spikes."""
    lo, hi = np.searchsorted(t, [t0, t1], side="left")
    n, t = np.asarray(n[lo:hi]), np.asarray(t[lo:hi])
    if neuron_mask is not None:
        keep = neuron_mask[n]
        n, t = n[keep], t[keep]
    truncated = len(n) > max_spikes
    return n[:max_spikes], t[:max_spikes], truncated


class LocalSpikeStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, experiment_id: str) -> Path:
        return self.root / _check_id(experiment_id)

    def save(self, experiment_id: str, neurons: np.ndarray, times: np.ndarray) -> None:
        """Write atomically: to a temporary folder, then rename."""
        final = self._dir(experiment_id)
        tmp = final.with_name(final.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        np.save(tmp / "neurons.npy", np.ascontiguousarray(neurons, dtype=np.int32))
        np.save(tmp / "times.npy", np.ascontiguousarray(times, dtype=np.float32))
        shutil.rmtree(final, ignore_errors=True)
        tmp.rename(final)

    def exists(self, experiment_id: str) -> bool:
        return (self._dir(experiment_id) / "times.npy").exists()

    def window(self, experiment_id: str, t0: float, t1: float,
               neuron_mask: np.ndarray | None, max_spikes: int) -> tuple[np.ndarray, np.ndarray, bool]:
        """Spikes with t0 <= t < t1 (times are sorted), optionally only masked neurons."""
        d = self._dir(experiment_id)
        times = np.load(d / "times.npy", mmap_mode="r")
        neurons = np.load(d / "neurons.npy", mmap_mode="r")
        return _select(neurons, times, t0, t1, neuron_mask, max_spikes)

    def delete(self, experiment_id: str) -> None:
        shutil.rmtree(self._dir(experiment_id), ignore_errors=True)


SpikeStore = LocalSpikeStore          # the default; kept under its old name


class S3SpikeStore:
    def __init__(self, bucket: str, prefix: str = "runs/", endpoint_url: str | None = None,
                 chunk_ms: float = 1000.0, client=None):
        import boto3
        self.s3 = client or boto3.client("s3", endpoint_url=endpoint_url or None)
        self.bucket = bucket
        self.prefix = prefix if prefix.endswith("/") or not prefix else prefix + "/"
        self.chunk_ms = chunk_ms

    def check(self) -> None:
        """Fail at startup, not after the first simulation, if the bucket isn't usable."""
        try:
            self.s3.head_bucket(Bucket=self.bucket)
        except Exception as e:
            raise RuntimeError(f"spike store: S3 bucket {self.bucket!r} is not reachable ({e}); "
                               "create it, or check FRUIT_FLY_S3_ENDPOINT and the AWS credentials") from e

    def _key(self, experiment_id: str, name: str) -> str:
        return f"{self.prefix}{_check_id(experiment_id)}/{name}"

    def save(self, experiment_id: str, neurons: np.ndarray, times: np.ndarray) -> None:
        self.delete(experiment_id)                      # no stale chunks from an earlier save
        neurons = np.ascontiguousarray(neurons, dtype=np.int32)
        times = np.ascontiguousarray(times, dtype=np.float32)
        chunk = np.floor(times / self.chunk_ms).astype(np.int64) if len(times) else np.zeros(0, np.int64)
        starts = np.flatnonzero(np.r_[True, chunk[1:] != chunk[:-1]]) if len(chunk) else np.zeros(0, int)
        ends = np.r_[starts[1:], len(chunk)]
        for a, b in zip(starts, ends):
            buf = io.BytesIO()
            np.savez(buf, neurons=neurons[a:b], times=times[a:b])
            self.s3.put_object(Bucket=self.bucket, Key=self._key(experiment_id, f"c{chunk[a]:06d}.npz"),
                               Body=buf.getvalue())
        meta = {"chunk_ms": self.chunk_ms, "chunks": [int(chunk[a]) for a in starts], "count": int(len(times))}
        self.s3.put_object(Bucket=self.bucket, Key=self._key(experiment_id, "meta.json"),
                           Body=json.dumps(meta).encode(), ContentType="application/json")

    def _meta(self, experiment_id: str) -> dict | None:
        try:
            body = self.s3.get_object(Bucket=self.bucket, Key=self._key(experiment_id, "meta.json"))["Body"]
        except self.s3.exceptions.NoSuchKey:
            return None
        return json.loads(body.read())

    def exists(self, experiment_id: str) -> bool:
        return self._meta(experiment_id) is not None

    def window(self, experiment_id: str, t0: float, t1: float,
               neuron_mask: np.ndarray | None, max_spikes: int) -> tuple[np.ndarray, np.ndarray, bool]:
        meta = self._meta(experiment_id)
        if meta is None:
            raise FileNotFoundError(f"no spikes stored for {experiment_id}")
        ms = meta["chunk_ms"]
        wanted = [c for c in meta["chunks"] if c * ms < t1 and (c + 1) * ms > t0]

        def fetch(c: int):
            body = self.s3.get_object(Bucket=self.bucket, Key=self._key(experiment_id, f"c{c:06d}.npz"))["Body"]
            with np.load(io.BytesIO(body.read())) as z:
                return z["neurons"], z["times"]

        with ThreadPoolExecutor(max_workers=8) as pool:   # chunks download in parallel
            parts = list(pool.map(fetch, wanted))
        if not parts:
            return np.zeros(0, np.int32), np.zeros(0, np.float32), False
        n = np.concatenate([p[0] for p in parts])
        t = np.concatenate([p[1] for p in parts])
        return _select(n, t, t0, t1, neuron_mask, max_spikes)

    def delete(self, experiment_id: str) -> None:
        prefix = self._key(experiment_id, "")
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": keys, "Quiet": True})


def make_spike_store(settings) -> LocalSpikeStore | S3SpikeStore:
    if settings.spike_store == "s3":
        return S3SpikeStore(settings.s3_bucket, settings.s3_prefix, settings.s3_endpoint)
    return LocalSpikeStore(settings.runs_dir)
