"""仅供测试的合成 mzML / mzXML。

这些峰不是仪器采集的。文件里写了 TEST ONLY SYNTHETIC NOT ACQUIRED。
生产界面不会调用本模块，安装包也不包含 tests 目录。
"""

from __future__ import annotations

import base64
import struct
from pathlib import Path


def _f64(values: list[float]) -> str:
    raw = struct.pack("<" + "d" * len(values), *values)
    return base64.b64encode(raw).decode("ascii")


def _array(name: str, accession: str, values: list[float]) -> str:
    encoded = _f64(values)
    return f"""
        <binaryDataArray encodedLength="{len(encoded)}">
          <cvParam cvRef="MS" accession="MS:1000523" name="64-bit float" value=""/>
          <cvParam cvRef="MS" accession="MS:1000576" name="no compression" value=""/>
          <cvParam cvRef="MS" accession="{accession}" name="{name}" value="" unitCvRef="MS" unitAccession="MS:1000040" unitName="m/z"/>
          <binary>{encoded}</binary>
        </binaryDataArray>"""


def _spectrum(index: int, scan: int, ms_level: int, polarity: str, rt_min: float,
              mz: list[float], intensity: list[float], *, extra_cv: list[tuple[str, str]] | None = None,
              precursor: dict | None = None, activation: str | None = None,
              collision_energy: float | None = None, sim: bool = False, srm: bool = False) -> str:
    polarity_cv = (
        '<cvParam cvRef="MS" accession="MS:1000130" name="positive scan" value=""/>'
        if polarity == "positive"
        else '<cvParam cvRef="MS" accession="MS:1000129" name="negative scan" value=""/>'
    )
    if srm:
        kind = '<cvParam cvRef="MS" accession="MS:1000583" name="SRM spectrum" value=""/>'
    elif sim:
        kind = '<cvParam cvRef="MS" accession="MS:1000582" name="SIM spectrum" value=""/>'
    elif ms_level == 1:
        kind = '<cvParam cvRef="MS" accession="MS:1000579" name="MS1 spectrum" value=""/>'
    else:
        kind = '<cvParam cvRef="MS" accession="MS:1000580" name="MSn spectrum" value=""/>'
    extra = ""
    for accession, name in extra_cv or []:
        extra += f'<cvParam cvRef="MS" accession="{accession}" name="{name}" value=""/>'
    precursor_xml = ""
    if precursor:
        lower = precursor.get("lower", 0.5)
        upper = precursor.get("upper", 0.5)
        act = ""
        if activation:
            act += f'<cvParam cvRef="MS" accession="MS:1000133" name="{activation}" value=""/>'
        if collision_energy is not None:
            act += (
                f'<cvParam cvRef="MS" accession="MS:1000045" name="collision energy" value="{collision_energy}" '
                'unitCvRef="UO" unitAccession="UO:0000266" unitName="electronvolt"/>'
            )
        precursor_xml = f"""
      <precursorList count="1">
        <precursor>
          <isolationWindow>
            <cvParam cvRef="MS" accession="MS:1000827" name="isolation window target m/z" value="{precursor['mz']}" unitCvRef="MS" unitAccession="MS:1000040" unitName="m/z"/>
            <cvParam cvRef="MS" accession="MS:1000828" name="isolation window lower offset" value="{lower}" unitCvRef="MS" unitAccession="MS:1000040" unitName="m/z"/>
            <cvParam cvRef="MS" accession="MS:1000829" name="isolation window upper offset" value="{upper}" unitCvRef="MS" unitAccession="MS:1000040" unitName="m/z"/>
          </isolationWindow>
          <selectedIonList count="1">
            <selectedIon>
              <cvParam cvRef="MS" accession="MS:1000744" name="selected ion m/z" value="{precursor['mz']}" unitCvRef="MS" unitAccession="MS:1000040" unitName="m/z"/>
              <cvParam cvRef="MS" accession="MS:1000041" name="charge state" value="{precursor.get('charge', 1)}"/>
            </selectedIon>
          </selectedIonList>
          <activation>{act}</activation>
        </precursor>
      </precursorList>"""
    tic = sum(intensity)
    bpc = max(intensity) if intensity else 0
    bpc_mz = mz[intensity.index(bpc)] if intensity else 0
    return f"""
    <spectrum index="{index}" id="scan={scan}" defaultArrayLength="{len(mz)}">
      {kind}
      <cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="{ms_level}"/>
      {polarity_cv}
      <cvParam cvRef="MS" accession="MS:1000127" name="centroid spectrum" value=""/>
      {extra}
      <cvParam cvRef="MS" accession="MS:1000285" name="total ion current" value="{tic}"/>
      <cvParam cvRef="MS" accession="MS:1000504" name="base peak m/z" value="{bpc_mz}"/>
      <cvParam cvRef="MS" accession="MS:1000505" name="base peak intensity" value="{bpc}"/>
      <scanList count="1">
        <cvParam cvRef="MS" accession="MS:1000795" name="no combination" value=""/>
        <scan>
          <cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="{rt_min}" unitCvRef="UO" unitAccession="UO:0000031" unitName="minute"/>
        </scan>
      </scanList>
      {precursor_xml}
      <binaryDataArrayList count="2">
        {_array("m/z array", "MS:1000514", mz)}
        {_array("intensity array", "MS:1000515", intensity)}
      </binaryDataArrayList>
    </spectrum>"""


def write_synthetic_mzml(path: Path) -> Path:
    """一张覆盖极性、DDA、DIA、SIM、SRM 和碰撞能量的合成文件。"""
    spectra = [
        _spectrum(0, 1, 1, "positive", 1.0, [100.0, 200.0, 300.0], [10.0, 30.0, 5.0]),
        _spectrum(1, 2, 1, "positive", 2.0, [100.0, 200.0], [20.0, 10.0]),
        _spectrum(2, 3, 1, "negative", 1.5, [150.0, 250.0], [7.0, 1.0]),
        _spectrum(3, 4, 2, "positive", 1.2, [50.0, 80.0, 120.0], [5.0, 9.0, 2.0],
                  extra_cv=[("MS:1003221", "data-dependent acquisition")],
                  precursor={"mz": 200.0, "charge": 1, "lower": 0.5, "upper": 0.5},
                  activation="collision-induced dissociation", collision_energy=20),
        _spectrum(4, 5, 2, "positive", 1.25, [50.0, 80.0], [1.0, 4.0],
                  extra_cv=[("MS:1003221", "data-dependent acquisition")],
                  precursor={"mz": 200.0, "charge": 1, "lower": 0.5, "upper": 0.5},
                  activation="beam-type collision-induced dissociation", collision_energy=40),
        _spectrum(5, 6, 2, "negative", 1.6, [40.0, 70.0], [3.0, 6.0],
                  extra_cv=[("MS:1003221", "data-dependent acquisition")],
                  precursor={"mz": 150.0, "charge": 1, "lower": 0.5, "upper": 0.5},
                  activation="collision-induced dissociation", collision_energy=20),
        _spectrum(6, 7, 2, "positive", 1.3, [90.0], [4.0],
                  extra_cv=[("MS:1003215", "data-independent acquisition")],
                  precursor={"mz": 500.0, "charge": 1, "lower": 10.0, "upper": 10.0},
                  activation="collision-induced dissociation", collision_energy=25),
        _spectrum(7, 8, 1, "positive", 1.4, [200.0], [100.0], sim=True),
        _spectrum(8, 9, 2, "positive", 1.7, [80.0], [50.0], srm=True,
                  precursor={"mz": 200.0, "charge": 1, "lower": 0.5, "upper": 0.5},
                  activation="collision-induced dissociation", collision_energy=20),
        _spectrum(9, 10, 2, "positive", 1.8, [55.0], [3.0],
                  precursor={"mz": 400.0, "charge": 1, "lower": 6.0, "upper": 6.0},
                  collision_energy=30),
        _spectrum(10, 11, 2, "positive", 1.9, [60.0], [2.0],
                  precursor={"mz": 600.0, "charge": 1, "lower": 40.0, "upper": 40.0},
                  collision_energy=30),
    ]
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<mzML xmlns="http://psi.hupo.org/ms/mzml" version="1.1.0">
  <cvList count="2">
    <cv id="MS" fullName="PSI-MS" version="4.1.0" URI="https://example.invalid/psi-ms.obo"/>
    <cv id="UO" fullName="Unit Ontology" version="1" URI="https://example.invalid/uo.obo"/>
  </cvList>
  <fileDescription>
    <fileContent>
      <cvParam cvRef="MS" accession="MS:1000579" name="MS1 spectrum" value=""/>
      <cvParam cvRef="MS" accession="MS:1000580" name="MSn spectrum" value=""/>
      <userParam name="comment" value="TEST ONLY SYNTHETIC NOT ACQUIRED"/>
    </fileContent>
  </fileDescription>
  <run id="synthetic-test-only">
    <spectrumList count="{len(spectra)}">
      {''.join(spectra)}
    </spectrumList>
  </run>
</mzML>
"""
    path.write_text(xml, encoding="utf-8")
    return path


def write_blank_mzml(path: Path) -> Path:
    """正离子空白：m/z 200 在 1 min 处较强，用来做空白标记测试。"""
    spectra = [
        _spectrum(0, 1, 1, "positive", 1.0, [100.0, 200.0], [1.0, 12.0]),
        _spectrum(1, 2, 1, "positive", 2.0, [100.0, 200.0], [1.0, 0.0]),
    ]
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<mzML xmlns="http://psi.hupo.org/ms/mzml" version="1.1.0">
  <fileDescription>
    <fileContent>
      <userParam name="comment" value="TEST ONLY SYNTHETIC NOT ACQUIRED blank"/>
    </fileContent>
  </fileDescription>
  <run id="synthetic-blank">
    <spectrumList count="{len(spectra)}">
      {''.join(spectra)}
    </spectrumList>
  </run>
</mzML>
"""
    path.write_text(xml, encoding="utf-8")
    return path


def write_synthetic_mzxml(path: Path) -> Path:
    def peaks(mz: list[float], intensity: list[float]) -> str:
        pairs: list[float] = []
        for left, right in zip(mz, intensity):
            pairs.extend([left, right])
        raw = struct.pack(">" + "f" * len(pairs), *pairs)
        return base64.b64encode(raw).decode("ascii")

    scan = f"""
    <scan num="1" msLevel="1" polarity="+" retentionTime="PT90.0S"
          basePeakMz="200" basePeakIntensity="30" totIonCurrent="45" peaksCount="2" centroided="1">
      <peaks precision="32" byteOrder="network" pairOrder="m/z-int" compressionType="none">{peaks([100.0, 200.0], [15.0, 30.0])}</peaks>
    </scan>
    <scan num="2" msLevel="2" polarity="-" retentionTime="PT120.0S"
          collisionEnergy="25" activationMethod="CID" precursorMz="150"
          basePeakMz="70" basePeakIntensity="6" totIonCurrent="9" peaksCount="2" centroided="1">
      <peaks precision="32" byteOrder="network" pairOrder="m/z-int" compressionType="none">{peaks([40.0, 70.0], [3.0, 6.0])}</peaks>
    </scan>
    """
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<mzXML>
  <msRun scanCount="2">
    <msInstrument>
      <msManufacturer category="msManufacturer" value="synthetic-test-only"/>
      <msModel category="msModel" value="TEST ONLY SYNTHETIC NOT ACQUIRED"/>
    </msInstrument>
    {scan}
  </msRun>
</mzXML>
"""
    path.write_text(xml, encoding="utf-8")
    return path
