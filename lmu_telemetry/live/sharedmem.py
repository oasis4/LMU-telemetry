"""Live telemetry from Le Mans Ultimate's own shared memory.

LMU ships a plugin SDK - ``Support/SharedMemoryInterface/`` inside the game
directory - and publishes its whole state into one mapping called
``LMU_Data``. The structs below are transcribed from *those* headers, on the
machine the game is installed on, and not from any third-party copy.

That choice matters. The widely used rF2 Shared Memory Map Plugin exposes
similar data under ``$rFactor2SMMP_*$``, and its layout is published - but the
published layout is the plugin's own repackaging at whatever version you
happen to have, and LMU's real ``TelemInfoV01`` has moved since: it carries
``mDeltaBest``, ``mBatteryChargeFraction`` and the boost-motor fields where
older transcriptions show padding. Reading with the wrong layout does not
fail. It returns numbers of the right type and the right order of magnitude,
in the wrong places.

Two things guard against that anyway:

* Every struct is checked against the mapping the game actually created. The
  game maps ``sizeof(SharedMemoryLayout)``; if this file disagrees, the
  transcription is wrong and opening fails rather than reporting nonsense.
* Every frame is checked for plausibility before it is believed - see
  :meth:`LiveTelemetry.sample`. A misaligned struct produces distances that
  jump, and jumps are refused.

**Packing.** ``InternalsPlugin.hpp`` wraps its ``V01`` structs in
``#pragma pack(push, 4)``. Left at natural alignment every ``double`` after
the first odd-sized field lands eight bytes late. The wrapper structs in
``SharedMemoryInterface.hpp`` come after the matching ``pop`` and are packed
normally, which is why only some of the classes below set ``_pack_``.

**Distance.** ``mLapDist`` lives on the scoring side, which the game updates
about five times a second. At 90 m/s that is 18 m between readings - coarser
than the 2 m grid everything downstream works on. So it is anchored, not
sampled: each scoring update replaces the figure outright, and speed carries
it the 200 ms in between. Anchoring rather than correcting is what stops
error accumulating over a lap.
"""

from __future__ import annotations

import ctypes

from .buffer import LiveSample

#: The game's mapping, and the event it signals a fresh frame with.
MAPPING = "LMU_Data"
#: Win32 FILE_MAP_READ, for asking whether the mapping is there at all.
FILE_MAP_READ = 0x0004
#: How many cars the layout has room for. From SharedMemoryInterface.hpp.
MAX_VEHICLES = 104
#: Number of entries in SharedMemoryEvent, which sizes the events array.
SME_MAX = 16
MAX_PATH = 260

#: A lap distance may not move further between two frames than this many
#: metres per second of elapsed time would allow. Le Mans' Mulsanne tops out
#: near 95 m/s; anything past this is a torn read or a wrong struct, not a car.
MAX_PLAUSIBLE_MS = 120.0


class SharedMemoryUnavailable(RuntimeError):
    """Raised when the game's mapping cannot be opened or does not fit."""


class Odometer:
    """How far round the lap the car is, at the rate the pedals arrive.

    ``mLapDist`` is a scoring field and scoring moves about five times a
    second - 18 m apart at 90 m/s, coarser than the 2 m grid everything
    downstream works on. So the figure is anchored on scoring and carried by
    speed in between.

    Each scoring update *replaces* the carried figure rather than correcting
    it. That is what stops the integration error building: no matter how long
    the reader runs, the error is only ever what accumulated since the last
    anchor, about 200 ms ago.

    Kept apart from :class:`LiveTelemetry` because this is the part with real
    behaviour in it, and it should be testable without the game running.
    """

    def __init__(self) -> None:
        self._lap: int | None = None
        self._anchor_m: float | None = None
        self._carried_m = 0.0
        self._at: float | None = None
        #: Set at the line: the distance the new lap must fall below before it
        #: has really begun. See :meth:`advance`.
        self._rolling_over_from: float | None = None

    def forget(self) -> None:
        """The car went away - to the menus, or to the pits from a replay.

        The lap number is forgotten along with the anchor. Clearing only the
        anchor leaves the next frame on a lap that matches with nothing behind
        it, which is a state the arithmetic below has no answer for.
        """
        self._lap = None
        self._anchor_m = None
        self._carried_m = 0.0
        self._at = None
        self._rolling_over_from = None

    def advance(
        self, lap_dist: float, lap: int, speed_ms: float, elapsed: float
    ) -> "float | None":
        """Where the car is now, or ``None`` if this frame cannot be true.

        The lap counter comes from telemetry at about 50 Hz and ``mLapDist``
        from scoring at about 5 Hz, so for up to 200 ms after the line the lap
        has advanced while the distance still belongs to the lap before it.
        Anchoring there starts the new lap at 5770 m, every corner is already
        behind the car, and the whole lap goes by in silence - which is what
        three laps at Monza did, findings for the first and nothing after.

        So a lap change does not anchor. It waits for the distance to fall
        below where it was, which is the line itself passing, and reports
        nothing until then. Two hundred milliseconds of no answer is the
        honest reading; the alternative is a confident wrong one.
        """
        if self._lap is not None and lap != self._lap:
            # Remember where we were, and say nothing until it wraps.
            self._rolling_over_from = self._anchor_m
            self._lap = lap
            self._anchor_m = None
            self._at = None
            self._carried_m = 0.0

        if self._rolling_over_from is not None:
            if lap_dist >= self._rolling_over_from:
                return None                      # scoring has not caught up
            self._rolling_over_from = None
            return self._anchor(lap_dist, lap, elapsed)

        if lap != self._lap or self._anchor_m is None or self._at is None:
            return self._anchor(lap_dist, lap, elapsed)

        step = elapsed - self._at
        if step < 0.0:
            # The session clock does not run backwards. This frame is torn.
            return None

        if lap_dist != self._anchor_m:
            # The allowance scales with the gap, or a stall in the reader
            # looks like a teleport. The constant term covers the case where
            # two frames carry the same elapsed time.
            #
            # Forward only. A car cannot appear 3 km further on, but it *can*
            # appear far behind, because that is the start/finish line - and
            # reading that as a bad frame is what wedged this permanently:
            # the anchor stayed at 5775 m, every later frame differed from it
            # by more than the allowance, and none was ever believed again.
            gap = lap_dist - self._anchor_m
            if gap > MAX_PLAUSIBLE_MS * (step + 0.25):
                return None
            return self._anchor(lap_dist, lap, elapsed)

        self._at = elapsed
        self._carried_m += speed_ms * step
        return self._anchor_m + self._carried_m

    def _anchor(self, lap_dist: float, lap: int, elapsed: float) -> float:
        self._lap = lap
        self._anchor_m = lap_dist
        self._carried_m = 0.0
        self._at = elapsed
        return lap_dist


# -- the game's structs, transcribed from Support/SharedMemoryInterface ------

class _Vec3(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double),
                ("z", ctypes.c_double)]


class _TelemWheel(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("mSuspensionDeflection", ctypes.c_double),
        ("mRideHeight", ctypes.c_double),
        ("mSuspForce", ctypes.c_double),
        ("mBrakeTemp", ctypes.c_double),
        ("mBrakePressure", ctypes.c_double),
        ("mRotation", ctypes.c_double),
        ("mLateralPatchVel", ctypes.c_double),
        ("mLongitudinalPatchVel", ctypes.c_double),
        ("mLateralGroundVel", ctypes.c_double),
        ("mLongitudinalGroundVel", ctypes.c_double),
        ("mCamber", ctypes.c_double),
        ("mLateralForce", ctypes.c_double),
        ("mLongitudinalForce", ctypes.c_double),
        ("mTireLoad", ctypes.c_double),
        ("mGripFract", ctypes.c_double),
        ("mPressure", ctypes.c_double),
        ("mTemperature", ctypes.c_double * 3),
        ("mWear", ctypes.c_double),
        ("mTerrainName", ctypes.c_char * 16),
        ("mSurfaceType", ctypes.c_ubyte),
        ("mFlat", ctypes.c_bool),
        ("mDetached", ctypes.c_bool),
        ("mStaticUndeflectedRadius", ctypes.c_ubyte),
        ("mVerticalTireDeflection", ctypes.c_double),
        ("mWheelYLocation", ctypes.c_double),
        ("mToe", ctypes.c_double),
        ("mTireCarcassTemperature", ctypes.c_double),
        ("mTireInnerLayerTemperature", ctypes.c_double * 3),
        ("mOptimalTemp", ctypes.c_float),
        ("mCompoundIndex", ctypes.c_ubyte),
        ("mCompoundType", ctypes.c_ubyte),
        ("mExpansion", ctypes.c_ubyte * 18),
    ]


class _TelemInfo(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("mID", ctypes.c_long),
        ("mDeltaTime", ctypes.c_double),
        ("mElapsedTime", ctypes.c_double),
        ("mLapNumber", ctypes.c_long),
        ("mLapStartET", ctypes.c_double),
        ("mVehicleName", ctypes.c_char * 64),
        ("mTrackName", ctypes.c_char * 64),
        ("mPos", _Vec3),
        ("mLocalVel", _Vec3),
        ("mLocalAccel", _Vec3),
        ("mOri", _Vec3 * 3),
        ("mLocalRot", _Vec3),
        ("mLocalRotAccel", _Vec3),
        ("mGear", ctypes.c_long),
        ("mEngineRPM", ctypes.c_double),
        ("mEngineWaterTemp", ctypes.c_double),
        ("mEngineOilTemp", ctypes.c_double),
        ("mClutchRPM", ctypes.c_double),
        ("mUnfilteredThrottle", ctypes.c_double),
        ("mUnfilteredBrake", ctypes.c_double),
        ("mUnfilteredSteering", ctypes.c_double),
        ("mUnfilteredClutch", ctypes.c_double),
        ("mFilteredThrottle", ctypes.c_double),
        ("mFilteredBrake", ctypes.c_double),
        ("mFilteredSteering", ctypes.c_double),
        ("mFilteredClutch", ctypes.c_double),
        ("mSteeringShaftTorque", ctypes.c_double),
        ("mFront3rdDeflection", ctypes.c_double),
        ("mRear3rdDeflection", ctypes.c_double),
        ("mFrontWingHeight", ctypes.c_double),
        ("mFrontRideHeight", ctypes.c_double),
        ("mRearRideHeight", ctypes.c_double),
        ("mDrag", ctypes.c_double),
        ("mFrontDownforce", ctypes.c_double),
        ("mRearDownforce", ctypes.c_double),
        ("mFuel", ctypes.c_double),
        ("mEngineMaxRPM", ctypes.c_double),
        ("mScheduledStops", ctypes.c_ubyte),
        ("mOverheating", ctypes.c_bool),
        ("mDetached", ctypes.c_bool),
        ("mHeadlights", ctypes.c_bool),
        ("mDentSeverity", ctypes.c_ubyte * 8),
        ("mLastImpactET", ctypes.c_double),
        ("mLastImpactMagnitude", ctypes.c_double),
        ("mLastImpactPos", _Vec3),
        ("mEngineTorque", ctypes.c_double),
        ("mCurrentSector", ctypes.c_long),
        ("mSpeedLimiter", ctypes.c_ubyte),
        ("mMaxGears", ctypes.c_ubyte),
        ("mFrontTireCompoundIndex", ctypes.c_ubyte),
        ("mRearTireCompoundIndex", ctypes.c_ubyte),
        ("mFuelCapacity", ctypes.c_double),
        ("mFrontFlapActivated", ctypes.c_ubyte),
        ("mRearFlapActivated", ctypes.c_ubyte),
        ("mRearFlapLegalStatus", ctypes.c_ubyte),
        ("mIgnitionStarter", ctypes.c_ubyte),
        ("mFrontTireCompoundName", ctypes.c_char * 18),
        ("mRearTireCompoundName", ctypes.c_char * 18),
        ("mSpeedLimiterAvailable", ctypes.c_ubyte),
        ("mAntiStallActivated", ctypes.c_ubyte),
        ("mUnused", ctypes.c_ubyte * 2),
        ("mVisualSteeringWheelRange", ctypes.c_float),
        ("mRearBrakeBias", ctypes.c_double),
        ("mTurboBoostPressure", ctypes.c_double),
        ("mPhysicsToGraphicsOffset", ctypes.c_float * 3),
        ("mPhysicalSteeringWheelRange", ctypes.c_float),
        # Fields below here are LMU's, and are where third-party transcriptions
        # of the older rF2 layout show one long padding array instead.
        ("mDeltaBest", ctypes.c_double),
        ("mBatteryChargeFraction", ctypes.c_double),
        ("mElectricBoostMotorTorque", ctypes.c_double),
        ("mElectricBoostMotorRPM", ctypes.c_double),
        ("mElectricBoostMotorTemperature", ctypes.c_double),
        ("mElectricBoostWaterTemperature", ctypes.c_double),
        ("mElectricBoostMotorState", ctypes.c_ubyte),
        ("mLapInvalidated", ctypes.c_bool),
        ("mABSActive", ctypes.c_bool),
        ("mTCActive", ctypes.c_bool),
        ("mSpeedLimiterActive", ctypes.c_bool),
        ("mWiperState", ctypes.c_uint8),
        ("mTC", ctypes.c_uint8),
        ("mTCMax", ctypes.c_uint8),
        ("mTCSlip", ctypes.c_uint8),
        ("mTCSlipMax", ctypes.c_uint8),
        ("mTCCut", ctypes.c_uint8),
        ("mTCCutMax", ctypes.c_uint8),
        ("mABS", ctypes.c_uint8),
        ("mABSMax", ctypes.c_uint8),
        ("mMotorMap", ctypes.c_uint8),
        ("mMotorMapMax", ctypes.c_uint8),
        ("mMigration", ctypes.c_uint8),
        ("mMigrationMax", ctypes.c_uint8),
        ("mFrontAntiSway", ctypes.c_uint8),
        ("mFrontAntiSwayMax", ctypes.c_uint8),
        ("mRearAntiSway", ctypes.c_uint8),
        ("mRearAntiSwayMax", ctypes.c_uint8),
        ("mLiftAndCoastProgress", ctypes.c_uint8),
        ("mTrackLimitsSteps", ctypes.c_uint8),
        ("mRegen", ctypes.c_float),
        ("mSoC", ctypes.c_float),
        ("mVirtualEnergy", ctypes.c_float),
        ("mTimeGapCarAhead", ctypes.c_float),
        ("mTimeGapCarBehind", ctypes.c_float),
        ("mTimeGapPlaceAhead", ctypes.c_float),
        ("mTimeGapPlaceBehind", ctypes.c_float),
        ("mVehicleModel", ctypes.c_char * 30),
        ("mVehicleClass", ctypes.c_uint8),
        ("mVehicleChampionship", ctypes.c_uint8),
        ("mExpansion", ctypes.c_ubyte * 20),
        ("mWheel", _TelemWheel * 4),
    ]


class _VehicleScoring(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("mID", ctypes.c_long),
        ("mDriverName", ctypes.c_char * 32),
        ("mVehicleName", ctypes.c_char * 64),
        ("mTotalLaps", ctypes.c_short),
        ("mSector", ctypes.c_byte),
        ("mFinishStatus", ctypes.c_byte),
        ("mLapDist", ctypes.c_double),
        ("mPathLateral", ctypes.c_double),
        ("mTrackEdge", ctypes.c_double),
        ("mBestSector1", ctypes.c_double),
        ("mBestSector2", ctypes.c_double),
        ("mBestLapTime", ctypes.c_double),
        ("mLastSector1", ctypes.c_double),
        ("mLastSector2", ctypes.c_double),
        ("mLastLapTime", ctypes.c_double),
        ("mCurSector1", ctypes.c_double),
        ("mCurSector2", ctypes.c_double),
        ("mNumPitstops", ctypes.c_short),
        ("mNumPenalties", ctypes.c_short),
        ("mIsPlayer", ctypes.c_bool),
        ("mControl", ctypes.c_byte),
        ("mInPits", ctypes.c_bool),
        ("mPlace", ctypes.c_ubyte),
        ("mVehicleClass", ctypes.c_char * 32),
        ("mTimeBehindNext", ctypes.c_double),
        ("mLapsBehindNext", ctypes.c_long),
        ("mTimeBehindLeader", ctypes.c_double),
        ("mLapsBehindLeader", ctypes.c_long),
        ("mLapStartET", ctypes.c_double),
        ("mPos", _Vec3),
        ("mLocalVel", _Vec3),
        ("mLocalAccel", _Vec3),
        ("mOri", _Vec3 * 3),
        ("mLocalRot", _Vec3),
        ("mLocalRotAccel", _Vec3),
        ("mHeadlights", ctypes.c_ubyte),
        ("mPitState", ctypes.c_ubyte),
        ("mServerScored", ctypes.c_ubyte),
        ("mIndividualPhase", ctypes.c_ubyte),
        ("mQualification", ctypes.c_long),
        ("mTimeIntoLap", ctypes.c_double),
        ("mEstimatedLapTime", ctypes.c_double),
        ("mPitGroup", ctypes.c_char * 24),
        ("mFlag", ctypes.c_ubyte),
        ("mUnderYellow", ctypes.c_bool),
        ("mCountLapFlag", ctypes.c_ubyte),
        ("mInGarageStall", ctypes.c_bool),
        ("mUpgradePack", ctypes.c_ubyte * 16),
        ("mPitLapDist", ctypes.c_float),
        ("mBestLapSector1", ctypes.c_float),
        ("mBestLapSector2", ctypes.c_float),
        ("mSteamID", ctypes.c_ulonglong),
        ("mVehFilename", ctypes.c_char * 32),
        ("mAttackMode", ctypes.c_short),
        ("mFuelFraction", ctypes.c_ubyte),
        ("mDRSState", ctypes.c_bool),
        ("mExpansion", ctypes.c_ubyte * 4),
    ]


class _ScoringInfo(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("mTrackName", ctypes.c_char * 64),
        ("mSession", ctypes.c_long),
        ("mCurrentET", ctypes.c_double),
        ("mEndET", ctypes.c_double),
        ("mMaxLaps", ctypes.c_long),
        ("mLapDist", ctypes.c_double),
        ("mResultsStream", ctypes.c_void_p),
        ("mNumVehicles", ctypes.c_long),
        ("mGamePhase", ctypes.c_ubyte),
        ("mYellowFlagState", ctypes.c_byte),
        ("mSectorFlag", ctypes.c_byte * 3),
        ("mStartLight", ctypes.c_ubyte),
        ("mNumRedLights", ctypes.c_ubyte),
        ("mInRealtime", ctypes.c_bool),
        ("mPlayerName", ctypes.c_char * 32),
        ("mPlrFileName", ctypes.c_char * 64),
        ("mDarkCloud", ctypes.c_double),
        ("mRaining", ctypes.c_double),
        ("mAmbientTemp", ctypes.c_double),
        ("mTrackTemp", ctypes.c_double),
        ("mWind", _Vec3),
        ("mMinPathWetness", ctypes.c_double),
        ("mMaxPathWetness", ctypes.c_double),
        ("mGameMode", ctypes.c_ubyte),
        ("mIsPasswordProtected", ctypes.c_bool),
        ("mServerPort", ctypes.c_ushort),
        ("mServerPublicIP", ctypes.c_ulong),
        ("mMaxPlayers", ctypes.c_long),
        ("mServerName", ctypes.c_char * 32),
        ("mStartET", ctypes.c_float),
        ("mAvgPathWetness", ctypes.c_double),
        ("mSessionTimeRemaining", ctypes.c_float),
        ("mTimeOfDay", ctypes.c_float),
        ("mIsFixedSetup", ctypes.c_bool),
        ("mTrackGripLevel", ctypes.c_uint8),
        ("mCloudCoverage", ctypes.c_uint8),
        ("mTrackLimitsStepsPerPenalty", ctypes.c_uint8),
        ("mTrackLimitsStepsPerPoint", ctypes.c_uint8),
        ("mExpansion", ctypes.c_ubyte * 187),
        ("mVehicle", ctypes.c_void_p),
    ]


class _AppState(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("mAppWindow", ctypes.c_void_p),
        ("mWidth", ctypes.c_ulong),
        ("mHeight", ctypes.c_ulong),
        ("mRefreshRate", ctypes.c_ulong),
        ("mWindowed", ctypes.c_ulong),
        ("mOptionsLocation", ctypes.c_ubyte),
        ("mOptionsPage", ctypes.c_char * 31),
        ("mExpansion", ctypes.c_ubyte * 204),
    ]


# The wrappers below live in SharedMemoryInterface.hpp, which is included after
# InternalsPlugin.hpp has popped its packing - so these are packed normally.

class _Generic(ctypes.Structure):
    _fields_ = [
        ("events", ctypes.c_uint32 * SME_MAX),
        ("gameVersion", ctypes.c_long),
        ("FFBTorque", ctypes.c_float),
        ("appInfo", _AppState),
    ]


class _PathData(ctypes.Structure):
    _fields_ = [
        ("userData", ctypes.c_char * MAX_PATH),
        ("customVariables", ctypes.c_char * MAX_PATH),
        ("stewardResults", ctypes.c_char * MAX_PATH),
        ("playerProfile", ctypes.c_char * MAX_PATH),
        ("pluginsFolder", ctypes.c_char * MAX_PATH),
    ]


class _ScoringData(ctypes.Structure):
    _fields_ = [
        ("scoringInfo", _ScoringInfo),
        ("scoringStreamSize", ctypes.c_size_t),
        ("vehScoringInfo", _VehicleScoring * MAX_VEHICLES),
        ("scoringStream", ctypes.c_char * 65536),
    ]


class _TelemetryData(ctypes.Structure):
    _fields_ = [
        ("activeVehicles", ctypes.c_uint8),
        ("playerVehicleIdx", ctypes.c_uint8),
        ("playerHasVehicle", ctypes.c_bool),
        ("telemInfo", _TelemInfo * MAX_VEHICLES),
    ]


class _ObjectOut(ctypes.Structure):
    _fields_ = [
        ("generic", _Generic),
        ("paths", _PathData),
        ("scoring", _ScoringData),
        ("telemetry", _TelemetryData),
    ]


class _MemoryInfo(ctypes.Structure):
    """VIRTUAL_MEMORY_BASIC_INFORMATION, enough of it to read RegionSize."""

    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.c_uint32),
        ("PartitionId", ctypes.c_uint16),
        ("RegionSize", ctypes.c_size_t),
        ("State", ctypes.c_uint32),
        ("Protect", ctypes.c_uint32),
        ("Type", ctypes.c_uint32),
    ]


def _kernel32():
    """kernel32 with the three calls this needs, typed.

    Typed rather than left to ctypes' defaults because every one of these
    returns or takes a pointer, and on 64-bit a handle truncated to a C int is
    a handle that closes something else.
    """
    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    dll.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    dll.OpenFileMappingW.restype = ctypes.c_void_p
    dll.MapViewOfFile.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_size_t,
    ]
    dll.MapViewOfFile.restype = ctypes.c_void_p
    dll.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    dll.CloseHandle.argtypes = [ctypes.c_void_p]
    dll.VirtualQuery.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_MemoryInfo), ctypes.c_size_t
    ]
    return dll


def mapping_exists(name: str) -> bool:
    """Whether *name* has been published by anything at all.

    Asked separately from mapping it, because "the game is not running" and
    "the game is running and these structs are the wrong size" are different
    problems with different fixes, and one failure blaming the game for both
    sends the reader off to restart something that was never wrong.
    """
    dll = _kernel32()
    handle = dll.OpenFileMappingW(FILE_MAP_READ, False, name)
    if not handle:
        return False
    dll.CloseHandle(handle)
    return True


class LiveTelemetry:
    """The player's car, one sample at a time, from the running game."""

    def __init__(self) -> None:
        expected = ctypes.sizeof(_ObjectOut)
        dll = _kernel32()

        # OpenFileMapping, never mmap. `mmap.mmap(-1, n, name)` does not open a
        # named mapping, it *creates* one - so against a name the game is not
        # publishing it quietly hands back a fresh page of zeros, and the panel
        # then shows a stationary car sitting confidently on the start line.
        # This call can only ever open something that already exists.
        handle = dll.OpenFileMappingW(FILE_MAP_READ, False, MAPPING)
        if not handle:
            raise SharedMemoryUnavailable(
                f"cannot find {MAPPING}. Le Mans Ultimate must be running and "
                f"in a session, on this machine and under this user account."
            )

        address = dll.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 0)
        if not address:
            error = ctypes.get_last_error()
            dll.CloseHandle(handle)
            raise SharedMemoryUnavailable(
                f"{MAPPING} is published but could not be mapped (error {error})."
            )

        info = _MemoryInfo()
        dll.VirtualQuery(address, ctypes.byref(info), ctypes.sizeof(info))
        actual = int(info.RegionSize)
        if actual < expected:
            dll.UnmapViewOfFile(address)
            dll.CloseHandle(handle)
            # Windows rounds a mapping up to a whole page, so the game's own
            # sizeof is somewhere in (actual - 4096, actual]. Coming in over
            # that means these structs are bigger than the game's, and every
            # value read past the first difference would be plausible and
            # wrong - so this is fatal rather than a warning.
            raise SharedMemoryUnavailable(
                f"{MAPPING} is {actual} bytes and this build needs {expected}. "
                f"The struct definitions in sharedmem.py do not match this "
                f"version of the game; re-transcribe them from "
                f"<LMU install>/Support/SharedMemoryInterface/."
            )

        self._dll = dll
        self._handle = handle
        self._address = address
        self._size = expected
        self._odometer = Odometer()

    def _read(self) -> _ObjectOut:
        # Copied out before it is read field by field. The game writes into
        # this while we look at it, and a struct read in place would mix two
        # frames together in the middle of a lap.
        return _ObjectOut.from_buffer_copy(
            ctypes.string_at(self._address, self._size)
        )

    def track_name(self) -> str:
        """The circuit the game has loaded, or "" when it has none.

        Read from scoring rather than from the player's telemetry entry, so it
        is answerable while the driver is still in the garage and no car is
        reporting - which is exactly when the overlay wants to know, because
        that is when it has time to go and find a reference lap.
        """
        raw = self._read().scoring.scoringInfo.mTrackName
        return raw.decode("utf-8", "replace").strip() if raw else ""

    def track_length_m(self) -> float:
        """How long the loaded course is, or 0.0 before one is loaded.

        The only thing that tells two layouts of one circuit apart. The name
        does not: Monza's full course and its Curva Grande variant are both
        "Autodromo Nazionale Monza" here, and there is no layout field
        anywhere in this mapping to ask instead.
        """
        return float(self._read().scoring.scoringInfo.mLapDist)

    def car_class(self) -> str:
        """The class the player's car is in, or "" if there is no car yet.

        A reference from another class is worse than none: a Hypercar lap at
        Monza is nine seconds under a GT3 one, and every corner would report
        the driver hopelessly off a target no GT3 can reach. It is the same
        self-reinforcing shape as the layout fault - "the quickest lap here"
        picks the quickest *car*, whatever is being driven.

        Taken from scoring so it answers from the garage, like the track name.
        """
        state = self._read()
        if not state.telemetry.playerHasVehicle:
            # Nothing is driving yet. Scoring still knows the field, but which
            # entry is the player is only answerable through telemetry.
            return ""
        car = state.telemetry.telemInfo[state.telemetry.playerVehicleIdx]
        entry = self._player_scoring(state, car.mID)
        if entry is None:
            return ""
        raw = entry.mVehicleClass
        return raw.decode("utf-8", "replace").strip() if raw else ""

    def sample(self) -> "tuple[LiveSample, int] | None":
        """One instant of the player's car and its lap number, or None.

        ``None`` while there is no car to report - in the menus, or on a frame
        whose distance moved further than any car could have. A jump means a
        torn read or a struct that does not match, and either way the frame is
        not something to steer a brake point by.
        """
        state = self._read()
        if not state.telemetry.playerHasVehicle:
            self._odometer.forget()
            return None

        car = state.telemetry.telemInfo[state.telemetry.playerVehicleIdx]
        scoring = self._player_scoring(state, car.mID)
        if scoring is None:
            self._odometer.forget()
            return None

        lap = int(car.mLapNumber)
        speed_ms = (
            car.mLocalVel.x ** 2 + car.mLocalVel.y ** 2 + car.mLocalVel.z ** 2
        ) ** 0.5
        if speed_ms > MAX_PLAUSIBLE_MS:
            return None

        elapsed = float(car.mElapsedTime)
        distance = self._odometer.advance(
            float(scoring.mLapDist), lap, speed_ms, elapsed
        )
        if distance is None:
            return None

        return (
            LiveSample(
                distance_m=distance,
                time_s=elapsed - float(car.mLapStartET),
                speed_kmh=speed_ms * 3.6,
                throttle=float(car.mUnfilteredThrottle),
                brake=float(car.mUnfilteredBrake),
                steering=float(car.mUnfilteredSteering),
                # The garage counts as the pits. A lap that touched either is
                # an out lap or an in lap, and comparing one against a
                # qualifying reference complains about a lap nobody was
                # setting a time on.
                in_pits=bool(scoring.mInPits) or bool(scoring.mInGarageStall),
            ),
            lap,
        )

    @staticmethod
    def _player_scoring(state: _ObjectOut, car_id: int):
        """The scoring entry for the same car the telemetry entry describes.

        Matched on ``mID`` rather than trusting the two arrays to be in the
        same order, which they need not be: telemetry is indexed by the game's
        own ``playerVehicleIdx`` and scoring by finishing order.
        """
        for i in range(min(state.scoring.scoringInfo.mNumVehicles, MAX_VEHICLES)):
            entry = state.scoring.vehScoringInfo[i]
            if entry.mID == car_id:
                return entry
        return None

    def close(self) -> None:
        """Both halves, and tolerant of being called twice."""
        address, self._address = getattr(self, "_address", None), None
        handle, self._handle = getattr(self, "_handle", None), None
        if address:
            self._dll.UnmapViewOfFile(address)
        if handle:
            self._dll.CloseHandle(handle)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
