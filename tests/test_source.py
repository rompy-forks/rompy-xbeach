from pathlib import Path
import pytest
import pandas as pd
import xarray as xr

from rompy_xbeach.source import (
    SourceGeotiff,
    SourceXYZ,
    SourceCRSDataset,
    SourceCRSFile,
    SourceCRSIntake,
    SourceOceantide,
    SourceCRSOceantide,
    SourceTimeseriesCSV,
    SourceTimeseriesDataFrame,
)


HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def csv_path():
    yield HERE / "data/wind.csv"


@pytest.fixture(scope="module")
def tif_path():
    yield HERE / "data/bathy.tif"


@pytest.fixture(scope="module")
def source():
    yield SourceGeotiff(filename=HERE / "data/bathy.tif")


def test_source_timeseries_csv(csv_path):
    source = SourceTimeseriesCSV(filename=csv_path, tcol="time")
    ds = source.open()
    assert "time" in ds.dims
    assert "wspd" in ds.data_vars


def test_source_timeseries_csv_parse_dates_in_kwargs(csv_path):
    source = SourceTimeseriesCSV(
        filename=csv_path, read_csv_kwargs=dict(parse_dates="datetime")
    )
    assert source.read_csv_kwargs["parse_dates"] == "datetime"


def test_source_timeseries_dataframe(csv_path):
    df = pd.read_csv(csv_path, parse_dates=["time"], index_col="time")
    source = SourceTimeseriesDataFrame(obj=df)
    ds = source.open()
    assert "time" in ds.dims
    assert "wspd" in ds.data_vars


def test_source_xyz():
    source = SourceXYZ(
        filename=HERE / "data/bathy_xyz.zip",
        read_csv_kwargs=dict(sep="\t"),
        xcol="easting",
        ycol="northing",
        zcol="elevation",
        crs=4326,
        res=0.0005,
    )
    ds = source.open()
    assert ds.rio.crs == 4326
    assert ds.rio.x_dim == "x"
    assert ds.rio.y_dim == "y"


def test_source_crs_dataset(tif_path):
    ds = xr.open_dataset(tif_path, engine="rasterio", band_as_variable=True)
    ds = ds.rio.reproject("epsg:28350").rename(x="easting", y="northing")
    source = SourceCRSDataset(obj=ds, crs=28350, x_dim="easting", y_dim="northing")
    ds2 = source.open()
    assert ds2.rio.crs == 28350
    assert ds2.rio.x_dim == "easting"
    assert ds2.rio.y_dim == "northing"


def test_source_crs_intake(tif_path):
    source = SourceCRSIntake(
        catalog_uri=tif_path.parent / "catalog.yaml",
        dataset_id="bathy_netcdf",
        crs=4326,
    )
    ds = source.open()
    assert ds.rio.crs == 4326
    assert ds.rio.x_dim == "x"
    assert ds.rio.y_dim == "y"


def test_source_crs_file(tif_path):
    source = SourceCRSFile(uri=tif_path, crs=4326)
    ds = source.open()
    assert ds.rio.crs == 4326
    assert ds.rio.x_dim == "x"
    assert ds.rio.y_dim == "y"


def test_source_oceantide():
    source = SourceOceantide(
        reader="read_otis_binary",
        kwargs=dict(
            gfile=HERE / "data/swaus_tide_cons/grid_m2s2n2k2k1o1p1q1mmmf",
            hfile=HERE / "data/swaus_tide_cons/h_m2s2n2k2k1o1p1q1mmmf",
            ufile=HERE / "data/swaus_tide_cons/u_m2s2n2k2k1o1p1q1mmmf",
        ),
    )
    assert hasattr(source.open(), "tide")


def test_source_crs_oceantide():
    source = SourceCRSOceantide(
        reader="read_otis_binary",
        kwargs=dict(
            gfile=HERE / "data/swaus_tide_cons/grid_m2s2n2k2k1o1p1q1mmmf",
            hfile=HERE / "data/swaus_tide_cons/h_m2s2n2k2k1o1p1q1mmmf",
            ufile=HERE / "data/swaus_tide_cons/u_m2s2n2k2k1o1p1q1mmmf",
        ),
        crs=4326,
    )
    assert hasattr(source.open(), "tide")
    assert source.open().rio.crs == 4326
