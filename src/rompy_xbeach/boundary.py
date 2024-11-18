"""XBeach wave boundary conditions."""

from abc import ABC, abstractmethod
from typing import Literal, Union, Optional, Annotated
from pathlib import Path
import logging
import numpy as np
import xarray as xr
from pydantic import BaseModel, Field, model_validator, field_validator

from wavespectra.core import select

from rompy.core.types import DatasetCoords, RompyBaseModel
from rompy.core.time import TimeRange
from rompy.core.boundary import BoundaryWaveStation
from rompy.core.data import DataGrid

from rompy_xbeach.source import SourceCRSFile, SourceCRSIntake, SourceCRSDataset, SourceCRSWavespectra
from rompy_xbeach.grid import RegularGrid, Ori
from rompy_xbeach.components.boundary import WaveBoundaryJons


logger = logging.getLogger(__name__)


SOURCE_PARAM_TYPES = Union[
    SourceCRSFile,
    SourceCRSIntake,
    SourceCRSDataset,
]

SOURCE_SPECTRA_TYPES = Union[
    SourceCRSWavespectra,
    SourceCRSFile,
    SourceCRSIntake,
    SourceCRSDataset,
]


def dspr_to_s(dspr: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Calculate the Jonswap spreading coefficient from the directional spread.

        Parameters
        ----------
        dspr: float | np.ndarray
            The directional spread in degrees.

        Returns
        -------
        s : float | np.ndarray
            The Jonswap spreading coefficient.

        """
        return (2 / np.radians(dspr)**2) - 1


class BCFile(RompyBaseModel):
    """Base class for writing XBeach boundary condition files."""

    bcfile: Optional[Path] = Field(
        default=None,
        description="Path to the boundary condition file",
    )
    filelist: Optional[Path] = Field(
        default=None,
        description="Path to the filelist file",
    )

    @model_validator(mode="after")
    def bcfile_or_filelist(self) -> "BCFile":
        if not any([self.bcfile, self.filelist]):
            raise ValueError("Either bcfile or filelist must be set")
        return self

    @property
    def namelist(self):
        """Return the namelist representation of the bcfile."""
        if self.filelist is not None:
            return dict(filelist=self.filelist.name)
        else:
            return dict(bcfile=self.bcfile.name)

    def write(self, destdir: str | Path) -> Path:
        """Write the boundary condition file to the destination directory.

        Parameters
        ----------
        destdir : str | Path
            Destination directory for the bcfile.

        Returns
        -------
        outfile : Path
            Path to the bcfile.

        """
        raise NotImplementedError


class BoundaryBase(DataGrid, ABC):
    """Base class for wave boundary interfaces."""
    model_type: Literal["boundary"] = Field(
        default="xbeach",
        description="Model type discriminator",
    )

    def _adjust_time(self, ds: xr.Dataset, time: TimeRange) -> xr.Dataset:
        """Modify the dataset so the start and end times are included.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset containing the boundary data to adjust.
        time : TimeRange
            The time range to adjust the dataset to.

        Returns
        -------
        dsout : xr.Dataset
            Dataset with the adjusted time range.

        """
        dsout = ds.sel(time=slice(time.start, time.end))
        kwargs = {"fill_value": "extrapolate"}
        times = ds.time.to_index().to_pydatetime()
        if time.start not in times:
            ds_start = ds.interp({self.coords.t: [time.start]}, kwargs=kwargs)
            dsout = xr.concat([ds_start, dsout], dim=self.coords.t)
        if time.end not in times:
            ds_end = ds.interp({self.coords.t: [time.end]}, kwargs=kwargs)
            dsout = xr.concat([dsout, ds_end], dim=self.coords.t)
        return dsout


class BoundaryBaseStation(BoundaryBase, ABC):
    """Base class to construct XBeach wave boundary from stations type data.

    This object provides similar functionality to the `BoundaryWaveStation` object in
    that it uses wavespectra to select points from a stations (non-gridded) type source
    data, but it also supports non-spectral data.

    Notes
    -----
    The `time_buffer` field is redefined from the base class to define new default
    values that ensure the time range is always buffered by one timestep.

    """

    model_type: Literal["station"] = Field(
        default="xbeach",
        description="Model type discriminator",
    )
    source: SOURCE_SPECTRA_TYPES = Field(
        description="Dataset source reader, must support CRS",
        discriminator="model_type",
    )
    sel_method: Literal["idw", "nearest"] = Field(
        default="idw",
        description=(
            "Defines which function from wavespectra.core.select to use for data "
            "selection: 'idw' uses sel_idw() for inverse distance weighting, "
            "'nearest' uses sel_nearest() for nearest neighbor selection"
        ),
    )
    sel_method_kwargs: dict = Field(
        default={},
        description="Keyword arguments for sel_method"
    )
    time_buffer: list[int] = Field(
        default=[1, 1],
        description=(
            "Number of source data timesteps to buffer the time range "
            "if `filter_time` is True"
        ),
    )

    @model_validator(mode="after")
    def validate_coords(self) -> "BoundaryBaseStation":
        ds = self.ds.copy()
        for coord in [self.coords.t, self.coords.s]:
            if coord not in ds.dims:
                raise ValueError(
                    f"Coordinate '{coord}' not in source dataset, "
                    f"available coordinates are {dict(ds.sizes)}"
                )
        for coord in [self.coords.x, self.coords.y]:
            if coord in ds.dims:
                raise ValueError(
                    f"'{coord}' must not be a dimension in the stations source "
                    f"dataset, but it is: {dict(ds.sizes)} - is this a gridded source?"
                )
            if coord not in ds.data_vars:
                raise ValueError(
                    f"'{coord}' must be a variable in the stations source dataset "
                    f"but available variables are {list(ds.data_vars)}"
                )
        return self

    def _boundary_points(self, grid: RegularGrid) -> Ori:
        """Return the x, y point of the offshore boundary in the source crs."""
        xoff, yoff = grid.offshore
        bnd = Ori(x=xoff, y=yoff, crs=grid.crs).reproject(self.source.crs)
        return bnd.x, bnd.y

    def _sel_boundary(self, grid) -> xr.Dataset:
        """Select the offshore boundary point from the source dataset."""
        xbnd, ybnd = self._boundary_points(grid=grid)
        ds = getattr(select, f"sel_{self.sel_method}")(
            self.ds,
            lons=xbnd,
            lats=ybnd,
            sitename=self.coords.s,
            lonname=self.coords.x,
            latname=self.coords.y,
            **self.sel_method_kwargs,
        )
        return ds

    def _validate_time(self, time):
        if self.coords.t not in self.source.coordinates:
            raise ValueError(f"Time coordinate {self.coords.t} not in source")
        t0, t1 = self.ds.time.to_index().to_pydatetime()[[0, -1]]
        if time.start < t0 or time.end > t1:
            raise ValueError(
                f"time range {time} outside of source time range {t0} - {t1}"
            )

    def get(
        self, destdir: str | Path, grid: RegularGrid, time: Optional[TimeRange] = None
    ) -> xr.Dataset:
        """Return a dataset with the boundary data.

        Parameters
        ----------
        destdir : str | Path
            Placeholder for the destination directory for saving the boundary data.
        grid: RegularGrid
            Grid instance to use for selecting the boundary points.
        time: TimeRange, optional
            The times to filter the data to, only used if `self.crop_data` is True.

        Returns
        -------
        ds: xr.Dataset
            The boundary dataset selected from the source. This method is abstract and
            must be implemented by the subclass to generate the expected bcfile output.

        Notes
        -----
        The `destdir` parameter is a placeholder for the output directory, but is not
        used in this method. The method is designed to return the dataset for further
        processing.

        """
        # Slice the times
        if self.crop_data and time is not None:
            self._validate_time(time)
            self._filter_time(time)
        # Select the boundary point
        return self._sel_boundary(grid)


class BoundaryStationJons(BoundaryBaseStation, ABC):
    """Base class for wave boundary from station type dataset such as SMC."""

    model_type: Literal["station_jons"] = Field(
        default="xbeach",
        description="Model type discriminator",
    )
    fnyq: Optional[float] = Field(
        default=None,
        description=(
            "Highest frequency used to create JONSWAP spectrum [Hz] "
            "(XBeach default: 0.3)"
        ),
        ge=0.2,
        le=1.0,
    )
    dfj: Optional[float] = Field(
        default=None,
        description=(
            "Step size frequency used to create JONSWAP spectrum [Hz] within the "
            "range fnyq/1000 - fnyq/20 (XBeach default: fnyq/200)"
        ),
    )
    filelist: Optional[bool] = Field(
        default=True,
        description=(
            "If True, create one bcfile for each timestep in the filtered dataset and "
            "return a FILELIST.txt file with the list of bcfiles, otherwise return a "
            "single bcfile with the wave parameters interpolated at time.start"
        )
    )
    dbtc: Optional[float] = Field(
        default=1.0,
        description=(
            "Timestep (s) used to describe time series of wave energy and long wave "
            "flux at offshore boundary"
        ),
        ge=0.1,
        le=2.0,
        examples=[1.0],
    )

    def _write_filelist(self, destdir: Path, bcfiles: list[str], durations: list[float]) -> Path:
        """Write a filelist with the bcfiles.

        Parameters
        ----------
        destdir : Path
            Destination directory for the filelist.
        bcfiles : list[Path]
            List of bcfiles to include in the filelist.
        durations : list[float]
            List of durations for each bcfile.

        Returns
        -------
        filename : Path
            Path to the filelist file.

        """
        filename = destdir / "filelist.txt"
        with open(filename, "w") as f:
            f.write("FILELIST\n")
            for bcfile, duration in zip(bcfiles, durations):
                f.write(f"{duration:g} {self.dbtc:g} {bcfile.name}\n")
        return filename

    def _instantiate_boundary(self, data: xr.Dataset) -> "BoundaryStationJons":
        """Instantiate the boundary object.

        Parameters
        ----------
        data : xr.Dataset
            Dataset containing single time for the boundary spectral data.

        """
        assert data.time.size == 1
        t = data.time.to_index().to_pydatetime()[0]
        logger.debug(f"Creating boundary for time {t}")
        kwargs = {}
        for param in ["hm0", "tp", "mainang", "gammajsp", "s"]:
            if param in data and not np.isnan(data[param]):
                kwargs[param] = float(data[param])
            elif param in data and np.isnan(data[param]):
                raise ValueError(f"Parameter {param} is NaN for {data.time}")
        bcfile = f"jons-{t:%Y%m%dT%H%M%S}.txt"
        return WaveBoundaryJons(bcfile=bcfile, fnyq=self.fnyq, dfj=self.dfj, **kwargs)

    def get(
        self, destdir: str | Path, grid: RegularGrid, time: Optional[TimeRange] = None
    ) -> dict:
        """Write the selected boundary data to file.

        Parameters
        ----------
        destdir : str | Path
            Destination directory for the netcdf file.
        grid : RegularGrid
            Grid instance to use for selecting the boundary points.
        time: TimeRange, optional
            The times to filter the data to, only used if `self.crop_data` is True.

        Returns
        -------
        outfile : Path
            Path to the boundary bcfile data.

        """
        ds = super().get(destdir, grid, time)
        if not self.filelist:
            # Write a single bcfile at the timerange start
            ds = ds.interp({self.coords.t: [time.start]})
            data = self._calculate_stats(ds)
            wb = self._instantiate_boundary(data)
            bcfile = BCFile(bcfile=wb.write(destdir))
        else:
            # Write a bcfile for each timestep in the timerange
            ds = self._adjust_time(ds, time)
            stats = self._calculate_stats(ds)
            times = stats.time.to_index().to_pydatetime()
            bcfiles = []
            durations = []
            for t0, t1 in zip(times[:-1], times[1:]):
                # Boundary data
                data = stats.sel(time=[t0])
                wb = self._instantiate_boundary(data)
                bcfiles.append(wb.write(destdir))
                # Boundary duration
                durations.append((t1 - t0).total_seconds())
            bcfile = BCFile(filelist=self._write_filelist(destdir, bcfiles, durations))
        return bcfile.namelist


class BoundaryStationSpectraJons(BoundaryStationJons):
    """Wave boundary conditions from station type spectra dataset such as SMC."""

    model_type: Literal["station_spectra_jons"] = Field(
        default="xbeach",
        description="Model type discriminator",
    )
    source: SOURCE_SPECTRA_TYPES = Field(
        description=(
            "Dataset source reader, must support CRS and have wavespectra accessor "
        ),
        discriminator="model_type",
    )
    coords: DatasetCoords = Field(
        default=DatasetCoords(x="lon", y="lat", t="time", s="site"),
        description="Names of the coordinates in the dataset",
    )

    @field_validator("source")
    def _validate_source_wavespectra(cls, source, values):
        if not hasattr(source.open(), "spec"):
            raise ValueError("source must have wavespectra accessor")
        return source

    def _calculate_stats(self, ds: xr.Dataset) -> xr.Dataset:
        """Calculate the wave statistics from the spectral data.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset containing the boundary spectral data.

        """
        stats = ds.spec.stats(["hs", "tp", "dpm", "gamma", "dspr"])
        stats["s"] = dspr_to_s(stats.dspr)
        return stats.rename(hs="hm0", dpm="mainang", gamma="gammajsp")

    def _write_filelist(self, destdir: Path, bcfiles: list[str], durations: list[float]) -> Path:
        """Write a filelist with the bcfiles.

        Parameters
        ----------
        destdir : Path
            Destination directory for the filelist.
        bcfiles : list[Path]
            List of bcfiles to include in the filelist.
        durations : list[float]
            List of durations for each bcfile.

        Returns
        -------
        filename : Path
            Path to the filelist file.

        """
        filename = destdir / "filelist.txt"
        with open(filename, "w") as f:
            f.write("FILELIST\n")
            for bcfile, duration in zip(bcfiles, durations):
                f.write(f"{duration:g} {self.dbtc:g} {bcfile.name}\n")
        return filename


# TODO: How to deal with Tp if only Fp is available?
# TODO: How to deal with NaN values in the source data?
class BoundaryStationParamJons(BoundaryStationJons):
    """Wave boundary conditions from station type parameters dataset such as SMC."""

    model_type: Literal["grid_param_jons"] = Field(
        default="grid_param_jons",
        description="Model type discriminator",
    )
    source: SOURCE_PARAM_TYPES = Field(
        description="Dataset source reader, must support CRS",
        discriminator="model_type",
    )
    hm0: Union[str, float] = Field(
        default="hs",
        description=(
            "Variable name of the significant wave height Hm0 in the source data, "
            "or alternatively a constant value to use for all times"
        )
    )
    tp: Union[str, float] = Field(
        default="tp",
        description=(
            "Variable name of the peak period Tp in the source data, "
            "or alternatively a constant value to use for all times"
        )
    )
    mainang: Union[str, float] = Field(
        default="dpm",
        description=(
            "Variable name of the main wave direction in the source data, "
            "or alternatively a constant  value to use for all times"
        )
    )
    gammajsp: Optional[Union[str, float]] = Field(
        default=None,
        description=(
            "Variable name of the gamma parameter in the source data, "
            "or alternatively a constant value to use for all times"
        )
    )
    dspr: Optional[Union[str, float]] = Field(
        default=None,
        description=(
            "Variable name of the directional spreading in the source data, used to "
            "calculate the Jonswap spreading coefficient, "
            "or alternatively a constant value to use for all times"
        )
    )

    def _calculate_stats(self, ds: xr.Dataset) -> xr.Dataset:
        """Calculate the wave statistics from the spectral data.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset containing the boundary spectral data.

        """
        stats = xr.Dataset()
        for param in ["hm0", "tp", "mainang", "gammajsp"]:
            if isinstance(getattr(self, param), str):
                stats[param] = ds[getattr(self, param)]
            elif isinstance:
                stats[param] = [getattr(self, param)] * ds.time.size
        if self.dspr is not None:
            if isinstance(self.dspr, str):
                stats["s"] = dspr_to_s(ds[self.dspr])
            elif isinstance(self.dspr, float):
                stats["s"] = dspr_to_s([self.dspr] * ds.time.size)
        return stats
