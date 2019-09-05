#
# This file is part of verify.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (http://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""Code for measuring metrics that apply to any Task.
"""

__all__ = ["TimingMetricConfig", "TimingMetricTask",
           "MemoryMetricConfig", "MemoryMetricTask",
           ]

import resource
import sys

import astropy.units as u

import lsst.pex.config as pexConfig

from lsst.verify import Measurement, Name
from lsst.verify.gen2tasks.metricRegistry import registerMultiple
from lsst.verify.tasks import MetricComputationError, MetadataMetricTask


class TimeMethodMetricConfig(MetadataMetricTask.ConfigClass):
    """Common config fields for metrics based on `~lsst.pipe.base.timeMethod`.

    These fields let metrics distinguish between different methods that have
    been decorated with `~lsst.pipe.base.timeMethod`.
    """
    target = pexConfig.Field(
        dtype=str,
        doc="The method to profile, optionally prefixed by one or more tasks "
            "in the format of `lsst.pipe.base.Task.getFullMetadata()`.")
    metric = pexConfig.Field(
        dtype=str,
        doc="The fully qualified name of the metric to store the "
            "profiling information.")


# Expose TimingMetricConfig name because config-writers expect it
TimingMetricConfig = TimeMethodMetricConfig


@registerMultiple("timing")
class TimingMetricTask(MetadataMetricTask):
    """A Task that computes a wall-clock time using metadata produced by the
    `lsst.pipe.base.timeMethod` decorator.

    Parameters
    ----------
    args
    kwargs
        Constructor parameters are the same as for
        `lsst.verify.gen2tasks.MetricTask`.
    """

    ConfigClass = TimingMetricConfig
    _DefaultName = "timingMetric"

    @classmethod
    def getInputMetadataKeys(cls, config):
        """Get search strings for the metadata.

        Parameters
        ----------
        config : ``cls.ConfigClass``
            Configuration for this task.

        Returns
        -------
        keys : `dict`
            A dictionary of keys, optionally prefixed by one or more tasks in
            the format of `lsst.pipe.base.Task.getFullMetadata()`.

             ``"StartTime"``
                 The key for when the target method started (`str`).
             ``"EndTime"``
                 The key for when the target method ended (`str`).
        """
        keyBase = config.target
        return {"StartTime": keyBase + "StartCpuTime",
                "EndTime": keyBase + "EndCpuTime"}

    def makeMeasurement(self, timings):
        """Compute a wall-clock measurement from metadata provided by
        `lsst.pipe.base.timeMethod`.

        Parameters
        ----------
        timings : `dict` [`str`, any]
            A representation of the metadata passed to `run`. The `dict` has
            the following keys:

             ``"StartTime"``
                 The time the target method started (`float` or `None`).
             ``"EndTime"``
                 The time the target method ended (`float` or `None`).

        Returns
        -------
        measurement : `lsst.verify.Measurement` or `None`
            The running time of the target method.

        Raises
        ------
        MetricComputationError
            Raised if the timing metadata are invalid.
        """
        if timings["StartTime"] is not None or timings["EndTime"] is not None:
            try:
                totalTime = timings["EndTime"] - timings["StartTime"]
            except TypeError:
                raise MetricComputationError("Invalid metadata")
            else:
                meas = Measurement(self.getOutputMetricName(self.config),
                                   totalTime * u.second)
                meas.notes['estimator'] = 'pipe.base.timeMethod'
                return meas
        else:
            self.log.info("Nothing to do: no timing information for %s found.",
                          self.config.target)
            return None

    @classmethod
    def getOutputMetricName(cls, config):
        return Name(config.metric)


# Expose MemoryMetricConfig name because config-writers expect it
MemoryMetricConfig = TimeMethodMetricConfig


@registerMultiple("memory")
class MemoryMetricTask(MetadataMetricTask):
    """A Task that computes the maximum resident set size using metadata
    produced by the `lsst.pipe.base.timeMethod` decorator.

    Parameters
    ----------
    args
    kwargs
        Constructor parameters are the same as for
        `lsst.verify.gen2tasks.MetricTask`.
    """

    ConfigClass = MemoryMetricConfig
    _DefaultName = "memoryMetric"

    @classmethod
    def getInputMetadataKeys(cls, config):
        """Get search strings for the metadata.

        Parameters
        ----------
        config : ``cls.ConfigClass``
            Configuration for this task.

        Returns
        -------
        keys : `dict`
            A dictionary of keys, optionally prefixed by one or more tasks in
            the format of `lsst.pipe.base.Task.getFullMetadata()`.

             ``"EndMemory"``
                 The key for the memory usage at the end of the method (`str`).
        """
        keyBase = config.target
        return {"EndMemory": keyBase + "EndMaxResidentSetSize"}

    def makeMeasurement(self, memory):
        """Compute a maximum resident set size measurement from metadata
        provided by `lsst.pipe.base.timeMethod`.

        Parameters
        ----------
        memory : `dict` [`str`, any]
            A representation of the metadata passed to `run`. Each `dict` has
            the following keys:

             ``"EndMemory"``
                 The memory usage at the end of the method (`int` or `None`).

        Returns
        -------
        measurement : `lsst.verify.Measurement` or `None`
            The maximum memory usage of the target method.

        Raises
        ------
        MetricComputationError
            Raised if the memory metadata are invalid.
        """
        if memory["EndMemory"] is not None:
            try:
                maxMemory = int(memory["EndMemory"])
            except (ValueError, TypeError) as e:
                raise MetricComputationError("Invalid metadata") from e
            else:
                meas = Measurement(self.getOutputMetricName(self.config),
                                   self._addUnits(maxMemory))
                meas.notes['estimator'] = 'pipe.base.timeMethod'
                return meas
        else:
            self.log.info("Nothing to do: no memory information for %s found.",
                          self.config.target)
            return None

    def _addUnits(self, memory):
        """Represent memory usage in correct units.

        Parameters
        ----------
        memory : `int`
            The memory usage as returned by `resource.getrusage`, in
            platform-dependent units.

        Returns
        -------
        memory : `astropy.units.Quantity`
            The memory usage in absolute units.
        """
        if sys.platform.startswith('darwin'):
            # MacOS uses bytes
            return memory * u.byte
        elif sys.platform.startswith('sunos') \
                or sys.platform.startswith('solaris'):
            # Solaris and SunOS use pages
            return memory * resource.getpagesize() * u.byte
        else:
            # Assume Linux, which uses kibibytes
            return memory * u.kibibyte

    @classmethod
    def getOutputMetricName(cls, config):
        return Name(config.metric)
