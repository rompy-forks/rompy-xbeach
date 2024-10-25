from pathlib import Path
import pytest
import xarray as xr

from rompy_xbeach.boundary import (
    WaveBoundaryBase,
    WaveBoundarySpectralJons,
    WaveBoundarySpectralJonstable,
)


HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def tif_path():
    yield HERE / "data/bathy.tif"


def test_wave_boundary_base():
    with pytest.raises(TypeError):
        WaveBoundaryBase()


def test_wave_boundary_spectral_defaults():
    wb = WaveBoundarySpectralJons()
    assert wb.bcfile == "spectrum.txt"
    assert wb.rt is None
    assert wb.dbtc is None
    assert wb.tm01switch is None
    assert wb.correcthm0 is None
    assert wb.dthetas_xb is None
    assert wb.fcutoff is None
    assert wb.nonhspectrum is None
    assert wb.nspectrumloc is None
    assert wb.nspr is None
    assert wb.random is None
    assert wb.sprdthr is None
    assert wb.trepfac is None
    assert wb.wbcversion is None


def test_wave_boundary_spectral_valid_ranges():
    with pytest.raises(ValueError):
        WaveBoundarySpectralJons(rt=1000)
        WaveBoundarySpectralJons(dbtc=2.1)
        WaveBoundarySpectralJons(dthetas_xb=-361)
        WaveBoundarySpectralJons(fcutoff=41.0)
        WaveBoundarySpectralJons(nspectrumloc=0)
        WaveBoundarySpectralJons(sprdthr=1.1)
        WaveBoundarySpectralJons(trepfac=-0.1)
        WaveBoundarySpectralJons(wbcversion=4)
        WaveBoundarySpectralJons(fnyq=1.0, dfj=0.01)


def test_wave_boundary_spectral_jons_valid_ranges():
    with pytest.raises(ValueError):
        WaveBoundarySpectralJons(fnyq=1.0, dfj=0.00099)
        WaveBoundarySpectralJons(fnyq=1.0, dfj=0.051)


def test_wave_boundary_spectral_jons_write(tmp_path):
    wb = WaveBoundarySpectralJons(hm0=1.0, tp=12.0, bcfile="jons.txt")
    bcfile = wb.write(tmp_path)
    assert bcfile.is_file()


def test_wave_boundary_spectral_jonstable_same_sizes():
    with pytest.raises(ValueError):
        WaveBoundarySpectralJonstable(
            hm0=[1.0, 2.0],
            tp=[10.0, 10.0],
            mainang=[180, 180],
            gammajsp=[3.3, 3.3],
            s=[10.0],
            duration=[1800, 1800],
            dtbc=[1.0, 1.0],
        )

def test_wave_boundary_spectral_jonstable_valid_ranges():
    with pytest.raises(ValueError):
        WaveBoundarySpectralJonstable(
            hm0=[1.0, 5000.0],
            tp=[10.0, 10.0],
            mainang=[180, 180],
            gammajsp=[3.3, 3.3],
            s=[10.0, 10.0],
            duration=[1800, 1800],
            dtbc=[1.0, 1.0],
        )

def test_wave_boundary_spectral_jonstable_write(tmp_path):
    wb = WaveBoundarySpectralJonstable(
        hm0=[1.0, 2.0],
        tp=[10.0, 10.0],
        mainang=[180, 180],
        gammajsp=[3.3, 3.3],
        s=[10.0, 10.0],
        duration=[1800, 1800],
        dtbc=[1.0, 1.0],
    )
    bcfile = wb.write(tmp_path)
    assert bcfile.is_file()

