using RfaMetadataAddin.Drainage;
using System;
using System.Collections.Generic;

internal static class DrainageEngineeringCoreTests
{
    private static int _failures;

    private static void Expect(bool condition, string name)
    {
        if (!condition)
        {
            _failures++;
            Console.Error.WriteLine("FAIL: " + name);
        }
    }

    public static int Main()
    {
        Expect(DrainageEngineeringCore.ResolveDownstreamEndpoint(10, 9, 100, "auto", 0.001) == 1, "lower end1");
        Expect(DrainageEngineeringCore.ResolveDownstreamEndpoint(9, 10, 100, "auto", 0.001) == 0, "lower end0");
        Expect(DrainageEngineeringCore.ResolveDownstreamEndpoint(10, 10, 100, "auto", 0.001) == -1, "flat unresolved");
        Expect(DrainageEngineeringCore.ResolveDownstreamEndpoint(10, 10, 100, "end0", 0.001) == 0, "user end0");
        Expect(
            DrainageEngineeringCore.SelectPreferredDownstreamCandidate(
                true,
                false,
                0,
                10) == 0,
            "physical feasibility overrides topology evidence");
        Expect(
            DrainageEngineeringCore.SelectPreferredDownstreamCandidate(
                true,
                true,
                2,
                4) == 1,
            "stronger topology evidence selects end1");
        Expect(
            DrainageEngineeringCore.SelectPreferredDownstreamCandidate(
                true,
                true,
                0,
                0) == 0,
            "ambiguous downstream uses stable end0 fallback");
        Expect(
            DrainageEngineeringCore.SelectPreferredDownstreamCandidate(
                false,
                false,
                4,
                2) == -1,
            "no feasible downstream candidate stays unresolved");
        Expect(DrainageEngineeringCore.IsExpectedDescendingSlope(10, 9, 100, 0.01, 0.000001), "one percent");
        Expect(!DrainageEngineeringCore.IsExpectedDescendingSlope(9, 10, 100, 0.01, 0.000001), "reverse fails");
        Expect(DrainageEngineeringCore.ClassifyConnectorAxis(0, 0, -1) == "vertical", "floor outlet");
        Expect(DrainageEngineeringCore.ClassifyConnectorAxis(1, 0, 0) == "horizontal", "wall outlet");
        Expect(DrainageEngineeringCore.IsDownwardConnectorAxis(0, 0, -1), "downward outlet");
        Expect(!DrainageEngineeringCore.IsDownwardConnectorAxis(0, 0, 1), "upward outlet rejected");
        Expect(
            DrainageEngineeringCore.IsNearlyVerticalDownwardAxis(
                0,
                0,
                -1),
            "exact downward source uses vertical solver");
        Expect(
            !DrainageEngineeringCore.IsNearlyVerticalDownwardAxis(
                Math.Cos(60 * Math.PI / 180.0),
                0,
                -Math.Sin(60 * Math.PI / 180.0)),
            "inclined downward source stays in general solver");
        Expect(
            !DrainageEngineeringCore.IsNearlyVerticalDownwardAxis(
                0,
                0,
                1),
            "upward source never uses vertical solver");
        Expect(
            DrainageEngineeringCore.IsConnectorAxisDirectedTowardTarget(1, 0, 5, 1, 0.1),
            "wall outlet points toward main");
        Expect(
            !DrainageEngineeringCore.IsConnectorAxisDirectedTowardTarget(-1, 0, 5, 1, 0.1),
            "wall outlet points away from main");
        Expect(
            Math.Abs(DrainageEngineeringCore.ComputeConnectorStubLength(100, 150, 2) - 200) < 0.000001,
            "stub respects diameter multiplier");
        Expect(DrainageEngineeringCore.IsMonotonicDescending(new List<double> { 10, 9.5, 9 }, 0.000001), "monotonic");
        Expect(!DrainageEngineeringCore.IsMonotonicDescending(new List<double> { 10, 9, 9.5 }, 0.000001), "local rise");
        Expect(
            Math.Abs(
                DrainageEngineeringCore
                    .ComputeGravityNearMainEndpointAdjustment(
                        9.88,
                        10.0,
                        12.0,
                        0.01))
                < 0.000001,
            "existing gravity slope reaches main at low end");
        Expect(
            Math.Abs(
                DrainageEngineeringCore
                    .ComputeGravityNearMainEndpointAdjustment(
                        10.0,
                        10.0,
                        12.0,
                        0.01)
                + 0.12)
                < 0.000001,
            "flat source lowers near-main end");
        Expect(
            Math.Abs(
                DrainageEngineeringCore
                    .ComputeGravityNearMainEndpointAdjustment(
                        10.12,
                        10.0,
                        12.0,
                        0.01)
                + 0.24)
                < 0.000001,
            "reverse source lowers near-main end past far end");
        Expect(
            DrainageEngineeringCore
                .IsGravitySlopeDirectedTowardMain(
                    9.88,
                    10.0,
                    12.0,
                    0.01,
                    0.000001),
            "gravity flow is directed toward selected main");
        Expect(
            !DrainageEngineeringCore
                .IsGravitySlopeDirectedTowardMain(
                    10.12,
                    10.0,
                    12.0,
                    0.01,
                    0.000001),
            "reverse gravity flow is rejected");
        Expect(
            Math.Abs(
                DrainageEngineeringCore
                    .ComputeSourceElevationAdjustmentLimit(
                        1500,
                        160,
                        100,
                        300)
                - 150)
                < 0.000001,
            "vertical compensation uses route-derived limit");
        Expect(Math.Abs(DrainageEngineeringCore.AngleBetween2D(1, 0, 1, 1) - 45) < 0.000001, "45 degree entry");
        Expect(
            DrainageEngineeringCore.IsDirectedSideEntryAllowed(
                1, 1, 1, 0, 45, 0.001),
            "directed downstream 45 entry");
        Expect(
            !DrainageEngineeringCore.IsDirectedSideEntryAllowed(
                -1, 1, 1, 0, 45, 0.001),
            "mirrored upstream 45 entry rejected");
        Expect(DrainageEngineeringCore.IsSideEntryAngleAllowed(45, 45, 2), "45 degree allowed");
        Expect(!DrainageEngineeringCore.IsSideEntryAngleAllowed(90, 45, 5), "90 degree rejected");
        Expect(Math.Abs(DrainageEngineeringCore.ComputeDownstreamShiftForFortyFive(-3.5) - 3.5) < 0.000001, "45 shift");
        Expect(
            Math.Abs(DrainageEngineeringCore.AngleBetween2D(3, -3, 1, 0) - 45) < 0.000001,
            "shifted tie yields downstream 45 entry");
        Expect(
            Math.Abs(DrainageEngineeringCore.AxialAngleDegrees(1, 0, 0, -1, 0, 0)) < 0.000001,
            "opposed run connectors are axially collinear");
        Expect(
            Math.Abs(DrainageEngineeringCore.AxialAngleDegrees(1, 1, 0, -1, 0, 0) - 45) < 0.000001,
            "wye branch connector has 45 axial angle");
        Expect(
            !DrainageEngineeringCore.IsSideEntryAngleAllowed(
                DrainageEngineeringCore.AxialAngleDegrees(0, 1, 0, 1, 0, 0),
                45,
                5),
            "tee branch connector is rejected");
        Expect(
            Math.Abs(DrainageEngineeringCore.RadialElevationAngleDegrees(1, 0, 0, 1, 0)) < 0.000001,
            "horizontal side entry radial angle");
        Expect(
            Math.Abs(DrainageEngineeringCore.RadialElevationAngleDegrees(1, 0, 0, 1, 1) - 45) < 0.000001,
            "45 degree upper-side radial angle");
        Expect(
            !DrainageEngineeringCore.IsRadialElevationAllowed(
                DrainageEngineeringCore.RadialElevationAngleDegrees(1, 0, 0, 0, 1),
                0,
                45,
                5),
            "top entry radial angle rejected");
        Expect(
            !DrainageEngineeringCore.IsRadialElevationAllowed(-10, 0, 45, 2),
            "bottom entry radial angle rejected");
        DrainageDoubleFortyFiveSolution offset = DrainageEngineeringCore
            .SolveDoubleFortyFiveOffset(100, 120, 20, 20, 50);
        Expect(offset.IsFeasible, "double 45 feasible");
        Expect(Math.Abs(offset.RunAdvance - 100) < 0.000001, "double 45 run advance");
        Expect(
            Math.Abs(offset.CenterlineDiagonalLength - Math.Sqrt(2) * 100) < 0.000001,
            "double 45 diagonal");
        Expect(
            DrainageEngineeringCore.SolveDoubleFortyFiveOffset(100, 99, 0, 0, 20)
                .FailureCode == "DOUBLE_45_INSUFFICIENT_RUN",
            "double 45 insufficient run");
        Expect(
            DrainageEngineeringCore.SolveDoubleFortyFiveOffset(100, 100, 60, 60, 30)
                .FailureCode == "DOUBLE_45_TANGENT_TOO_SHORT",
            "double 45 tangent too short");
        Expect(
            DrainageEngineeringCore.SolveDoubleFortyFiveOffset(0, 100, 0, 0, 20)
                .FailureCode == "DOUBLE_45_INPUT_INVALID",
            "double 45 invalid input");
        Expect(
            DrainageEngineeringCore.IsPipeSegmentLengthAllowed(200, 50, 50, 100),
            "minimum tangent exact");
        Expect(
            !DrainageEngineeringCore.IsPipeSegmentLengthAllowed(199, 50, 50, 100),
            "minimum tangent rejected");
        Expect(
            DrainageEngineeringCore.IsAxisDirectedTowardTarget3D(
                1, 0, -0.01, 10, 0, -0.1, 0.99),
            "downstream fitting axis mapped");
        Expect(
            !DrainageEngineeringCore.IsAxisDirectedTowardTarget3D(
                -1, 0, 0.01, 10, 0, -0.1, 0.99),
            "upstream axis is not downstream");
        var wallInput = new DrainageWallRouteInput
        {
            Source = new DrainageGeometryPoint { X = 0, Y = 0, Z = 500 },
            OutletX = 0,
            OutletY = 1,
            MainStart = new DrainageGeometryPoint { X = -2000, Y = 1000, Z = 0 },
            MainEnd = new DrainageGeometryPoint { X = 2000, Y = 1000, Z = 0 },
            DownstreamEndpointIndex = 1,
            SlopeRatio = 0.01,
            StubLength = 100,
            ElbowTakeout = 20,
            JunctionBranchTakeout = 30,
            MinimumTangentLength = 50,
            MainEndClearance = 100,
            MaximumOutletAdvance = 900,
            SearchStep = 1
        };
        var singleInput = new DrainageWallRouteInput
        {
            Source = new DrainageGeometryPoint
            {
                X = 0,
                Y = 0,
                Z = 7.0710678119
            },
            OutletX = 0,
            OutletY = 1,
            OutletZ = 0,
            MainStart = new DrainageGeometryPoint
            {
                X = -2000,
                Y = 1000,
                Z = 0
            },
            MainEnd = new DrainageGeometryPoint
            {
                X = 2000,
                Y = 1000,
                Z = 0
            },
            DownstreamEndpointIndex = 1,
            SlopeRatio = 0.01,
            StubLength = 100,
            ElbowTakeout = 20,
            JunctionBranchTakeout = 30,
            MinimumTangentLength = 50,
            MainEndClearance = 100,
            MaximumOutletAdvance = 2000,
            SearchStep = 1
        };
        Expect(
            !DrainageEngineeringCore
                .IsSourceBelowTargetMainAtPlanProjection(
                    singleInput,
                    0.001),
            "source above projected main is allowed");
        var belowMainInput = new DrainageWallRouteInput
        {
            Source = new DrainageGeometryPoint
            {
                X = 0,
                Y = 0,
                Z = -10
            },
            OutletX = 0,
            OutletY = 1,
            OutletZ = 0,
            MainStart = singleInput.MainStart,
            MainEnd = singleInput.MainEnd,
            DownstreamEndpointIndex = 1,
            SlopeRatio = 0.01,
            StubLength = 100,
            ElbowTakeout = 20,
            JunctionBranchTakeout = 30,
            MinimumTangentLength = 50,
            MainEndClearance = 100,
            MaximumOutletAdvance = 2000,
            SearchStep = 1
        };
        Expect(
            DrainageEngineeringCore
                .IsSourceBelowTargetMainAtPlanProjection(
                    belowMainInput,
                    0.001),
            "source below projected main is detected");
        Expect(
            DrainageEngineeringCore
                .SolveSingleFortyFive(belowMainInput)
                .FailureCode == "SOURCE_BELOW_TARGET_MAIN",
            "source below main returns stable failure");
        DrainageSingleFortyFiveSolution singleRoute =
            DrainageEngineeringCore
                .SolveSingleFortyFive(singleInput);
        Expect(
            singleRoute.IsFeasible,
            "single 45 route feasible");
        Expect(
            singleRoute.IsFeasible
                && Math.Abs(
                    singleRoute.ElbowAngleDegrees - 45)
                    <= 0.01,
            "single 45 elbow angle");
        Expect(
            singleRoute.IsFeasible
                && singleRoute.StubEnd.Z
                    >= singleRoute.MainTie.Z,
            "single 45 monotonic");
        Expect(
            singleRoute.IsFeasible
                && Math.Abs(singleRoute.MainTie.Z)
                    < 0.000001,
            "single 45 ties at main elevation");
        DrainageSingleFortyFiveSolution repeatedSingleRoute =
            DrainageEngineeringCore
                .SolveSingleFortyFive(singleInput);
        Expect(
            singleRoute.IsFeasible
                && repeatedSingleRoute.IsFeasible
                && Math.Abs(
                    singleRoute.StubEnd.X
                    - repeatedSingleRoute.StubEnd.X)
                    < 0.000001
                && Math.Abs(
                    singleRoute.MainTie.X
                    - repeatedSingleRoute.MainTie.X)
                    < 0.000001,
            "single 45 result is deterministic");
        singleInput.MinimumTangentLength = 2000;
        Expect(
            !DrainageEngineeringCore
                .SolveSingleFortyFive(singleInput)
                .IsFeasible,
            "single 45 minimum tangent enforced");
        singleInput.MinimumTangentLength = 50;
        singleInput.OutletX = 1;
        singleInput.OutletY = 0;
        Expect(
            !DrainageEngineeringCore
                .SolveSingleFortyFive(singleInput)
                .IsFeasible,
            "single 45 rejects incompatible outlet");
        singleInput.OutletX = 0;
        singleInput.OutletY = 1;

        var perpendicularDropInput = new DrainageWallRouteInput
        {
            Source = new DrainageGeometryPoint
            {
                X = 0,
                Y = 0,
                Z = 500
            },
            OutletX = 0,
            OutletY = 1,
            OutletZ = 0,
            MainStart = new DrainageGeometryPoint
            {
                X = -2000,
                Y = 1000,
                Z = 0
            },
            MainEnd = new DrainageGeometryPoint
            {
                X = 2000,
                Y = 1000,
                Z = 0
            },
            DownstreamEndpointIndex = 1,
            SlopeRatio = 0.01,
            StubLength = 100,
            ElbowTakeout = 20,
            JunctionBranchTakeout = 30,
            MinimumTangentLength = 50,
            MainEndClearance = 100,
            MaximumOutletAdvance = 2000,
            SearchStep = 1
        };
        DrainagePerpendicularDropSolution perpendicularDrop =
            DrainageEngineeringCore
                .SolvePerpendicularDropEntry(
                    perpendicularDropInput);
        Expect(
            perpendicularDrop.IsFeasible,
            "perpendicular high branch can drop into lower main: "
                + perpendicularDrop.FailureCode);
        Expect(
            perpendicularDrop.IsFeasible
                && perpendicularDrop.StubEnd.Z
                    > perpendicularDrop.MainTie.Z
                && perpendicularDrop.EntrySlope > 0.01
                && perpendicularDrop.ElbowAngleDegrees > 45
                && perpendicularDrop.ElbowAngleDegrees < 88,
            "perpendicular drop keeps arbitrary descending entry slope");
        Expect(
            perpendicularDrop.IsFeasible
                && Math.Abs(
                    DrainageEngineeringCore.AngleBetween2D(
                        perpendicularDrop.MainTie.X
                            - perpendicularDrop.StubEnd.X,
                        perpendicularDrop.MainTie.Y
                            - perpendicularDrop.StubEnd.Y,
                        1,
                        0)
                    - 45.0) < 0.001,
            "perpendicular drop enters the main downstream at forty-five degrees in plan");
        DrainagePerpendicularDropSolution repeatedPerpendicularDrop =
            DrainageEngineeringCore
                .SolvePerpendicularDropEntry(
                    perpendicularDropInput);
        Expect(
            perpendicularDrop.IsFeasible
                && repeatedPerpendicularDrop.IsFeasible
                && Math.Abs(
                    perpendicularDrop.MainTie.X
                        - repeatedPerpendicularDrop.MainTie.X)
                    < 0.000001
                && Math.Abs(
                    perpendicularDrop.MainTie.Z
                        - repeatedPerpendicularDrop.MainTie.Z)
                    < 0.000001,
            "perpendicular drop result is deterministic");
        var adjustablePerpendicularInput =
            new DrainageWallRouteInput
            {
                Source = new DrainageGeometryPoint
                {
                    X = 0,
                    Y = 0,
                    Z = 340
                },
                OutletX = 0,
                OutletY = 1,
                OutletZ = -0.01,
                MainStart = new DrainageGeometryPoint
                {
                    X = -1000,
                    Y = 1174,
                    Z = 0
                },
                MainEnd = new DrainageGeometryPoint
                {
                    X = 1000,
                    Y = 1174,
                    Z = 0
                },
                DownstreamEndpointIndex = 1,
                SlopeRatio = 0.01,
                StubLength = 160,
                ElbowTakeout = 32,
                JunctionBranchTakeout = 145,
                MinimumTangentLength = 80,
                MainEndClearance = 100,
                MaximumOutletAdvance = 2000,
                SearchStep = 5,
                AllowSourceAxialAdjustment = true
            };
        DrainagePerpendicularDropSolution
            adjustablePerpendicular =
                DrainageEngineeringCore
                    .SolvePerpendicularDropEntry(
                        adjustablePerpendicularInput);
        Expect(
            adjustablePerpendicular.IsFeasible
                && adjustablePerpendicular
                    .SourceAxialAdjustment > 0
                && adjustablePerpendicular.StubEnd.Z
                    > adjustablePerpendicular.MainTie.Z,
            "perpendicular drop extends an open pipe end before the downstream diagonal entry");
        adjustablePerpendicularInput
            .MainForbiddenIntervals =
                new List<DrainageMainForbiddenInterval>
                {
                    new DrainageMainForbiddenInterval
                    {
                        MinimumParameter = 0.45,
                        MaximumParameter = 1.0,
                        ElementId = 98765
                    }
                };
        DrainagePerpendicularDropSolution
            blockedPerpendicular =
                DrainageEngineeringCore
                    .SolvePerpendicularDropEntry(
                        adjustablePerpendicularInput);
        Expect(
            !blockedPerpendicular.IsFeasible
                && blockedPerpendicular.FailureCode
                    == "TARGET_FITTING_CLEARANCE_CONFLICT"
                && blockedPerpendicular.BlockingElementId
                    == 98765,
            "perpendicular drop reports the blocking target fitting: "
                + blockedPerpendicular.FailureCode
                + " / "
                + blockedPerpendicular.BlockingElementId);
        adjustablePerpendicularInput
            .MainForbiddenIntervals = null;
        adjustablePerpendicularInput
            .AllowSourceAxialAdjustment = false;
        Expect(
            DrainageEngineeringCore
                    .SolvePerpendicularDropEntry(
                        adjustablePerpendicularInput)
                    .FailureCode
                == "TARGET_SEGMENT_CAPACITY_INSUFFICIENT",
            "fixed source end reports target segment capacity instead of generic tangent space");
        perpendicularDropInput.AllowSourceAxialAdjustment =
            true;
        perpendicularDropInput.MaximumSourceAxialAdjustment =
            800;
        DrainagePerpendicularDropSolution
            compactPerpendicularDrop =
                DrainageEngineeringCore
                    .SolvePerpendicularDropEntry(
                        perpendicularDropInput);
        DrainagePerpendicularDropSolution
            repeatedCompactPerpendicularDrop =
                DrainageEngineeringCore
                    .SolvePerpendicularDropEntry(
                        perpendicularDropInput);
        Expect(
            compactPerpendicularDrop.IsFeasible
                && compactPerpendicularDrop
                    .SourceAxialAdjustment > 0
                && compactPerpendicularDrop
                    .VariableRouteLength
                    < perpendicularDrop.VariableRouteLength,
            "perpendicular drop ranks a materially shorter adjustable route");
        Expect(
            repeatedCompactPerpendicularDrop.IsFeasible
                && Math.Abs(
                    compactPerpendicularDrop
                        .SourceAxialAdjustment
                    - repeatedCompactPerpendicularDrop
                        .SourceAxialAdjustment)
                    < 0.000001
                && Math.Abs(
                    compactPerpendicularDrop
                        .VariableRouteLength
                    - repeatedCompactPerpendicularDrop
                        .VariableRouteLength)
                    < 0.000001,
            "compact perpendicular route ranking is deterministic");
        var fittingAwarePerpendicularInput =
            new DrainageWallRouteInput
            {
                Source = new DrainageGeometryPoint
                {
                    X = 154161.7518,
                    Y = 51018.8287,
                    Z = -4617.0624
                },
                OutletX = 0,
                OutletY = -1,
                OutletZ = -0.01,
                MainStart = new DrainageGeometryPoint
                {
                    X = 153461.2393,
                    Y = 50000,
                    Z = -4834.6124
                },
                MainEnd = new DrainageGeometryPoint
                {
                    X = 156303.6370,
                    Y = 50000,
                    Z = -4863.0364
                },
                DownstreamEndpointIndex = 1,
                SlopeRatio = 0.01,
                StubLength = 160,
                ElbowTakeout = 80,
                JunctionBranchTakeout = 132.27,
                JunctionBranchAngleDegrees = 45,
                SideEntryAngleDegrees = 45,
                SideEntryToleranceDegrees = 5,
                RadialMinimumDegrees = 0,
                RadialMaximumDegrees = 45,
                RadialToleranceDegrees = 5,
                JunctionBranchAxisMinimumAlignment = 0.95,
                MinimumTangentLength = 80,
                MainEndClearance = 230,
                MaximumOutletAdvance = 25000,
                ExistingSourceLength = 1706.323,
                SearchStep = 5,
                AllowSourceAxialAdjustment = true,
                MaximumSourceAxialAdjustment = 1000
            };
        DrainagePerpendicularDropSolution
            fittingAwarePerpendicularDrop =
                DrainageEngineeringCore
                    .SolvePerpendicularDropEntry(
                        fittingAwarePerpendicularInput);
        Expect(
            fittingAwarePerpendicularDrop.IsFeasible
                && fittingAwarePerpendicularDrop
                    .SourceAxialAdjustment > 0
                && fittingAwarePerpendicularDrop
                    .SourceAxialAdjustment < 630,
            "fitting-aware ranking skips the shortest junction-invalid candidate: "
                + fittingAwarePerpendicularDrop.FailureCode
                + " / "
                + fittingAwarePerpendicularDrop
                    .SourceAxialAdjustment);
        DrainagePerpendicularDropSolution
            repeatedFittingAwarePerpendicularDrop =
                DrainageEngineeringCore
                    .SolvePerpendicularDropEntry(
                        fittingAwarePerpendicularInput);
        Expect(
            repeatedFittingAwarePerpendicularDrop.IsFeasible
                && Math.Abs(
                    fittingAwarePerpendicularDrop
                        .SourceAxialAdjustment
                    - repeatedFittingAwarePerpendicularDrop
                        .SourceAxialAdjustment)
                    < 0.000001,
            "fitting-aware perpendicular route remains deterministic");
        perpendicularDropInput.AllowSourceAxialAdjustment =
            false;
        perpendicularDropInput.MaximumSourceAxialAdjustment =
            null;
        perpendicularDropInput.MaximumPerpendicularDropLength =
            1000;
        perpendicularDropInput.MaximumPerpendicularDropRouteShare =
            0.40;
        perpendicularDropInput.ExistingSourceLength = 1000;
        DrainagePerpendicularDropSolution boundedPerpendicularDrop =
            DrainageEngineeringCore
                .SolvePerpendicularDropEntry(
                    perpendicularDropInput);
        Expect(
            boundedPerpendicularDrop.IsFeasible
                && boundedPerpendicularDrop
                    .ExceedsPreferredLength
                && boundedPerpendicularDrop
                    .ExceedsPreferredRouteShare,
            "long direct drop remains feasible and reports preferred-bound warnings");
        Expect(
            DrainageEngineeringCore
                    .SolveSingleFortyFive(
                        perpendicularDropInput)
                    .IsFeasible
                || DrainageEngineeringCore
                    .SolveWallOutletGeneralDoubleFortyFive(
                        perpendicularDropInput)
                    .IsFeasible,
            "long direct drop can fall back to a fitting-valid routed candidate");
        perpendicularDropInput.ExistingSourceLength = 5000;
        Expect(
            DrainageEngineeringCore
                .SolvePerpendicularDropEntry(
                    perpendicularDropInput)
                .IsFeasible,
            "long direct drop remains available when it is a bounded share of the full branch");
        perpendicularDropInput.MaximumPerpendicularDropLength =
            null;
        perpendicularDropInput.MaximumPerpendicularDropRouteShare =
            null;
        perpendicularDropInput.ExistingSourceLength = 0;
        perpendicularDropInput.OutletX = 1;
        perpendicularDropInput.OutletY = 0;
        Expect(
            DrainageEngineeringCore
                .SolvePerpendicularDropEntry(
                    perpendicularDropInput)
                .FailureCode
                == "PERPENDICULAR_DROP_SOURCE_NOT_PERPENDICULAR",
            "perpendicular drop rejects a source parallel to the main");
        perpendicularDropInput.OutletX = 0;
        perpendicularDropInput.OutletY = 1;
        perpendicularDropInput.Source.Z = -100;
        Expect(
            DrainageEngineeringCore
                .SolvePerpendicularDropEntry(
                    perpendicularDropInput)
                .FailureCode
                == "PERPENDICULAR_DROP_MAIN_NOT_LOWER",
            "perpendicular drop rejects a main above the branch");
        perpendicularDropInput.Source.Z = 500;

        var directInput = new DrainageWallRouteInput
        {
            Source = new DrainageGeometryPoint
            {
                X = -500,
                Y = 500,
                Z = 7.0710678119
            },
            OutletX = 1,
            OutletY = 1,
            OutletZ = -0.0141421356,
            MainStart = singleInput.MainStart,
            MainEnd = singleInput.MainEnd,
            DownstreamEndpointIndex = 1,
            SlopeRatio = 0.01,
            StubLength = 100,
            ElbowTakeout = 20,
            JunctionBranchTakeout = 30,
            MinimumTangentLength = 50,
            MainEndClearance = 100,
            MaximumOutletAdvance = 2000,
            SearchStep = 1
        };
        DrainageAxisDirectSolution directRoute =
            DrainageEngineeringCore
                .SolveAxisDirect(directInput);
        Expect(
            directRoute.IsFeasible,
            "axis direct route feasible");
        Expect(
            directRoute.IsFeasible
                && Math.Abs(
                    directRoute.JunctionAngleDegrees - 45)
                    <= 0.01,
            "axis direct junction angle");
        Expect(
            directRoute.IsFeasible
                && Math.Abs(directRoute.MainTie.Z)
                    < 0.000001,
            "axis direct ties at main elevation");
        directInput.OutletZ = 0;
        Expect(
            DrainageEngineeringCore
                .SolveAxisDirect(directInput)
                .FailureCode
                == "AXIS_DIRECT_SLOPE_MISMATCH",
            "axis direct requires signed profile slope");

        var shortHorizontalInput = new DrainageWallRouteInput
        {
            Source = new DrainageGeometryPoint
            {
                X = 0,
                Y = 0,
                Z = 0
            },
            OutletX = 0,
            OutletY = -1,
            OutletZ = 0,
            MainStart = new DrainageGeometryPoint
            {
                X = 8000,
                Y = -1473.75,
                Z = -86
            },
            MainEnd = new DrainageGeometryPoint
            {
                X = -2000,
                Y = -1473.75,
                Z = 14
            },
            DownstreamEndpointIndex = 0,
            SlopeRatio = 0.01,
            StubLength = 160,
            ElbowTakeout = 43.06,
            JunctionBranchTakeout = 94,
            MinimumTangentLength = 80,
            MainEndClearance = 150,
            MaximumOutletAdvance = 25000,
            MaximumDouble45LateralOffset = 25,
            SearchStep = 5
        };
        DrainageSingleFortyFiveSolution shortHorizontalSingle =
            DrainageEngineeringCore.SolveSingleFortyFive(
                shortHorizontalInput);
        DrainageWallRouteSolution shortHorizontalDouble =
            DrainageEngineeringCore
                .SolveWallOutletGeneralDoubleFortyFive(
                    shortHorizontalInput);
        Expect(
            !shortHorizontalSingle.IsFeasible,
            "single 45 rejects outlet overshoot and return");
        Expect(
            shortHorizontalSingle.FailureCode
                == "SINGLE45_TANGENT_TOO_SHORT",
            "single 45 reports forward route tangent shortage");
        Expect(
            !shortHorizontalDouble.IsFeasible
                && shortHorizontalDouble.FailureCode
                    == "DOUBLE_45_TANGENT_TOO_SHORT",
            "short horizontal case has no constructible double 45");
        double boundedAdjustment;
        Expect(
            DrainageEngineeringCore
                .TryComputeBoundedElevationCompensation(
                    0,
                    -6,
                    100,
                    1,
                    out boundedAdjustment)
                && Math.Abs(boundedAdjustment + 6)
                    < 0.000001,
            "small main-slope elevation datum is compensated");
        Expect(
            !DrainageEngineeringCore
                .TryComputeBoundedElevationCompensation(
                    0,
                    -250,
                    100,
                    1,
                    out boundedAdjustment),
            "large elevation mismatch is never compensated");
        shortHorizontalInput.Source.Z = -5;
        Expect(
            DrainageEngineeringCore
                .SolveSingleFortyFive(shortHorizontalInput)
                .IsFeasible
                || DrainageEngineeringCore
                .SolveWallOutletGeneralDoubleFortyFive(
                    shortHorizontalInput)
                .IsFeasible,
            "one-millimeter head above the projected main avoids degenerate geometry");
        shortHorizontalInput.Source.Z = 0;

        var verticalSourceInput = new DrainageWallRouteInput
        {
            Source = new DrainageGeometryPoint
            {
                X = 0,
                Y = 0,
                Z = 0
            },
            OutletX = 0,
            OutletY = 0,
            OutletZ = -1,
            MainStart = new DrainageGeometryPoint
            {
                X = -5000,
                Y = -4000,
                Z = -300
            },
            MainEnd = new DrainageGeometryPoint
            {
                X = 5000,
                Y = -4000,
                Z = -400
            },
            DownstreamEndpointIndex = 1,
            SlopeRatio = 0.01,
            StubLength = 160,
            ElbowTakeout = 43.06,
            JunctionBranchTakeout = 94,
            MinimumTangentLength = 80,
            MainEndClearance = 150,
            MaximumOutletAdvance = 25000,
            MaximumDouble45LateralOffset = 25,
            SearchStep = 5
        };
        DrainageWallRouteSolution verticalSourceRoute =
            DrainageEngineeringCore
                .SolveWallOutletGeneralDoubleFortyFive(
                    verticalSourceInput);
        Expect(
            verticalSourceRoute.IsFeasible,
            "vertical source route remains feasible");
        Expect(
            verticalSourceRoute.IsFeasible
                && Math.Abs(verticalSourceRoute.StubEnd.X)
                    < 0.000001
                && Math.Abs(verticalSourceRoute.StubEnd.Y)
                    < 0.000001
                && verticalSourceRoute.StubEnd.Z < 0,
            "vertical source first descends on connector axis");
        Expect(
            verticalSourceRoute.IsFeasible
                && verticalSourceRoute.OutletAdvance
                    > verticalSourceInput.StubLength
                && verticalSourceRoute.DiagonalTangentLength
                    <= verticalSourceInput.MinimumTangentLength
                        + 0.000001,
            "vertical source maximizes axial descent before offset");
        verticalSourceInput.Source.Z = 1000;
        DrainageTerminalDropSolution terminalDropRoute =
            DrainageEngineeringCore
                .SolveVerticalTerminalDropRoute(
                    verticalSourceInput);
        Expect(
            terminalDropRoute.IsFeasible,
            "vertical source terminal-drop route remains feasible: "
                + terminalDropRoute.FailureCode);
        Expect(
            terminalDropRoute.IsFeasible
                && terminalDropRoute.UpperBranchTangentLength
                    > terminalDropRoute.TerminalDropTangentLength
                && terminalDropRoute.UpperBranchTangentLength
                    >= terminalDropRoute.BranchTangentLength
                        + verticalSourceInput.MinimumTangentLength
                        - 0.000001,
            "terminal-drop route keeps the long run before the localized descent");
        Expect(
            terminalDropRoute.IsFeasible
                && terminalDropRoute.BranchTangentLength
                    >= Math.Max(
                        verticalSourceInput.MinimumTangentLength,
                        verticalSourceInput.MainEndClearance)
                        - 0.000001
                && terminalDropRoute.TerminalDropStart.Z
                    > terminalDropRoute.BranchStart.Z
                && terminalDropRoute.BranchStart.Z
                    > terminalDropRoute.MainTie.Z,
            "terminal-drop route descends near the main and keeps a constructible final approach");
        Expect(
            terminalDropRoute.IsFeasible
                && terminalDropRoute.PlanTurnAngleDegrees
                    >= 30.0 - 0.000001
                && terminalDropRoute.PlanTurnAngleDegrees
                    <= 75.0 + 0.000001,
            "terminal-drop route may vary its plan direction while preserving fitting angles");
        Expect(
            terminalDropRoute.IsFeasible
                && Math.Abs(
                    DrainageEngineeringCore.AxialAngleDegrees(
                        terminalDropRoute.StubEnd.X
                            - verticalSourceInput.Source.X,
                        terminalDropRoute.StubEnd.Y
                            - verticalSourceInput.Source.Y,
                        terminalDropRoute.StubEnd.Z
                            - verticalSourceInput.Source.Z,
                        terminalDropRoute.UpperBranchStart.X
                            - terminalDropRoute.StubEnd.X,
                        terminalDropRoute.UpperBranchStart.Y
                            - terminalDropRoute.StubEnd.Y,
                        terminalDropRoute.UpperBranchStart.Z
                            - terminalDropRoute.StubEnd.Z)
                    - 45.0) < 1.0
                && Math.Abs(
                    DrainageEngineeringCore.AxialAngleDegrees(
                        terminalDropRoute.UpperBranchStart.X
                            - terminalDropRoute.StubEnd.X,
                        terminalDropRoute.UpperBranchStart.Y
                            - terminalDropRoute.StubEnd.Y,
                        terminalDropRoute.UpperBranchStart.Z
                            - terminalDropRoute.StubEnd.Z,
                        terminalDropRoute.TerminalDropStart.X
                            - terminalDropRoute.UpperBranchStart.X,
                        terminalDropRoute.TerminalDropStart.Y
                            - terminalDropRoute.UpperBranchStart.Y,
                        terminalDropRoute.TerminalDropStart.Z
                            - terminalDropRoute.UpperBranchStart.Z)
                    - 45.0) < 1.0
                && Math.Abs(
                    DrainageEngineeringCore.AxialAngleDegrees(
                        terminalDropRoute.TerminalDropStart.X
                            - terminalDropRoute.UpperBranchStart.X,
                        terminalDropRoute.TerminalDropStart.Y
                            - terminalDropRoute.UpperBranchStart.Y,
                        terminalDropRoute.TerminalDropStart.Z
                            - terminalDropRoute.UpperBranchStart.Z,
                        terminalDropRoute.BranchStart.X
                            - terminalDropRoute.TerminalDropStart.X,
                        terminalDropRoute.BranchStart.Y
                            - terminalDropRoute.TerminalDropStart.Y,
                        terminalDropRoute.BranchStart.Z
                            - terminalDropRoute.TerminalDropStart.Z)
                    - 45.0) < 1.0
                && Math.Abs(
                    DrainageEngineeringCore.AxialAngleDegrees(
                        terminalDropRoute.BranchStart.X
                            - terminalDropRoute.TerminalDropStart.X,
                        terminalDropRoute.BranchStart.Y
                            - terminalDropRoute.TerminalDropStart.Y,
                        terminalDropRoute.BranchStart.Z
                            - terminalDropRoute.TerminalDropStart.Z,
                        terminalDropRoute.MainTie.X
                            - terminalDropRoute.BranchStart.X,
                        terminalDropRoute.MainTie.Y
                            - terminalDropRoute.BranchStart.Y,
                        terminalDropRoute.MainTie.Z
                            - terminalDropRoute.BranchStart.Z)
                    - 45.0) < 1.0,
            "terminal-drop route uses four genuine forty-five-degree elbows");
        verticalSourceInput.Source.Z = 0;
        var boundedVerticalCompensationInput =
            new DrainageWallRouteInput
            {
                Source = new DrainageGeometryPoint
                {
                    X = 155000,
                    Y = 64000,
                    Z = -4500
                },
                OutletX = 0,
                OutletY = 0,
                OutletZ = -1,
                MainStart = new DrainageGeometryPoint
                {
                    X = 150000,
                    Y = 60000,
                    Z = -4800
                },
                MainEnd = new DrainageGeometryPoint
                {
                    X = 160000,
                    Y = 60000,
                    Z = -4900
                },
                DownstreamEndpointIndex = 1,
                SlopeRatio = 0.01,
                StubLength = 160,
                ElbowTakeout = 43.06,
                JunctionBranchTakeout = 94,
                MinimumTangentLength = 80,
                VerticalTransitionMinimumTangentLength = 160,
                VerticalTransitionMinimumOutletAdvanceLength = 100,
                MainEndClearance = 150,
                MaximumOutletAdvance = 25000,
                MaximumDouble45LateralOffset = 25,
                SearchStep = 1
            };
        DrainageTerminalDropSolution uncompensatedVerticalRoute =
            DrainageEngineeringCore
                .SolveVerticalTerminalDropRoute(
                    boundedVerticalCompensationInput);
        Expect(
            !uncompensatedVerticalRoute.IsFeasible
                && uncompensatedVerticalRoute.FailureCode
                    == "TERMINAL_DROP_INSUFFICIENT_VERTICAL_FALL",
            "model vertical source reports insufficient vertical fall before compensation");
        DrainageVerticalPlanTurnSolution preferredVerticalRoute =
            DrainageEngineeringCore
                .SolveVerticalPlanTurnRoute(
                    boundedVerticalCompensationInput);
        double preferredVerticalFinalHorizontalLength = Math.Sqrt(
            Math.Pow(
                preferredVerticalRoute.MainTie.X
                    - preferredVerticalRoute.PlanTurnStart.X,
                2)
            + Math.Pow(
                preferredVerticalRoute.MainTie.Y
                    - preferredVerticalRoute.PlanTurnStart.Y,
                2));
        double preferredVerticalRadialHorizontalLength = Math.Sqrt(
            Math.Pow(
                preferredVerticalRoute.PlanTurnStart.X
                    - preferredVerticalRoute.RadialStart.X,
                2)
            + Math.Pow(
                preferredVerticalRoute.PlanTurnStart.Y
                    - preferredVerticalRoute.RadialStart.Y,
                2));
        Expect(
            preferredVerticalRoute.IsFeasible
                && preferredVerticalRoute.OutletAdvance
                    >= boundedVerticalCompensationInput
                        .VerticalTransitionMinimumOutletAdvanceLength
                        - 0.000001
                && preferredVerticalRoute
                    .SourceDiagonalTangentLength
                    >= boundedVerticalCompensationInput
                        .VerticalTransitionMinimumTangentLength
                        - 0.000001
                && preferredVerticalRoute.RadialTangentLength
                    >= boundedVerticalCompensationInput
                        .MinimumTangentLength
                        - 0.000001
                && preferredVerticalRoute
                    .FinalBranchTangentLength
                    >= boundedVerticalCompensationInput
                        .MinimumTangentLength
                        - 0.000001,
            "model vertical source preserves source double-45, radial run, and final plan-45 approach");
        Expect(
            preferredVerticalRoute.IsFeasible
                && preferredVerticalFinalHorizontalLength
                    > 0.000001
                && Math.Abs(
                    (preferredVerticalRoute.PlanTurnStart.Z
                        - preferredVerticalRoute.MainTie.Z)
                    / preferredVerticalFinalHorizontalLength
                    - boundedVerticalCompensationInput.SlopeRatio)
                    < 0.000001
                && preferredVerticalRadialHorizontalLength
                    > 0.000001
                && Math.Abs(
                    (preferredVerticalRoute.RadialStart.Z
                        - preferredVerticalRoute.PlanTurnStart.Z)
                    / preferredVerticalRadialHorizontalLength
                    - boundedVerticalCompensationInput.SlopeRatio)
                    < 0.000001,
            "vertical radial and final approach runs both carry the configured one-percent signed slope");
        Expect(
            preferredVerticalRoute.IsFeasible
                && Math.Abs(
                    preferredVerticalRoute
                        .FirstElbowAngleDegrees
                    - 45.0) < 1.0
                && Math.Abs(
                    preferredVerticalRoute
                        .SecondElbowAngleDegrees
                    - 45.0) < 1.0
                && Math.Abs(
                    preferredVerticalRoute
                        .PlanTurnAngleDegrees
                    - 45.0) < 0.000001,
            "vertical route uses source double-45 and a separate plan 45 turn");
        boundedVerticalCompensationInput.Source.Z += 100;
        Expect(
            DrainageEngineeringCore
                .SolveVerticalTerminalDropRoute(
                    boundedVerticalCompensationInput)
                .IsFeasible,
            "one-hundred-millimeter vertical endpoint compensation makes the model route feasible");
        DrainageWallRouteSolution wall =
            DrainageEngineeringCore.SolveWallOutletDoubleFortyFive(wallInput);
        Expect(wall.IsFeasible, "wall double 45 route feasible");
        Expect(
            wall.StubEnd.Z >= wall.OffsetEnd.Z
                && wall.OffsetEnd.Z >= wall.BranchStart.Z
                && wall.BranchStart.Z > wall.MainTie.Z,
            "wall double 45 monotonic elevations");
        Expect(
            Math.Abs(wall.PlanTurnAngleDegrees - 45) < 0.000001,
            "wall plan turn is 45 degrees");
        wallInput.OutletX = Math.Cos(30 * Math.PI / 180.0);
        wallInput.OutletY = Math.Sin(30 * Math.PI / 180.0);
        Expect(
            DrainageEngineeringCore.SolveWallOutletDoubleFortyFive(wallInput)
                .FailureCode == "WALL_PLAN_TURN_UNSUPPORTED",
            "unsupported wall plan turn rejected");
        wallInput.OutletX = 0;
        wallInput.OutletY = 1;
        wallInput.StubLength = 60;
        Expect(
            DrainageEngineeringCore.SolveWallOutletDoubleFortyFive(wallInput)
                .FailureCode == "WALL_STUB_TANGENT_TOO_SHORT",
            "wall stub tangent rejected");
        wallInput.StubLength = 100;
        DrainageWallRouteSolution generalWall =
            DrainageEngineeringCore
                .SolveWallOutletGeneralDoubleFortyFive(wallInput);
        Expect(generalWall.IsFeasible, "general wall double 45 feasible");
        Expect(
            generalWall.IsFeasible
                && Math.Abs(
                    generalWall.MainTie.Z) < 0.000001,
            "different elevation route ties at main elevation");
        Expect(
            generalWall.StubEnd.Z <= wallInput.Source.Z + 0.000001
                && generalWall.OffsetEnd.Z
                    <= generalWall.StubEnd.Z + 0.000001
                && generalWall.MainTie.Z
                    <= generalWall.OffsetEnd.Z + 0.000001,
            "general wall route monotonic");
        Expect(
            generalWall.DiagonalTangentLength >=
                wallInput.MinimumTangentLength,
            "general wall middle tangent");
        Expect(
            generalWall.BranchTangentLength >=
                wallInput.MinimumTangentLength,
            "general wall terminal tangent");
        wallInput.OutletX = 0;
        wallInput.OutletY = 0;
        wallInput.OutletZ = -1;
        DrainageWallRouteSolution floorRoute =
            DrainageEngineeringCore
                .SolveWallOutletGeneralDoubleFortyFive(wallInput);
        Expect(floorRoute.IsFeasible, "floor double 45 feasible");
        Expect(
            Math.Abs(floorRoute.StubEnd.X - wallInput.Source.X)
                < 0.000001
                && Math.Abs(
                    floorRoute.StubEnd.Y - wallInput.Source.Y)
                    < 0.000001
                && floorRoute.StubEnd.Z < wallInput.Source.Z,
            "floor first tangent follows downward connector");
        Expect(
            Math.Abs(DrainageEngineeringCore.AxialAngleDegrees(
                floorRoute.StubEnd.X - wallInput.Source.X,
                floorRoute.StubEnd.Y - wallInput.Source.Y,
                floorRoute.StubEnd.Z - wallInput.Source.Z,
                floorRoute.OffsetEnd.X - floorRoute.StubEnd.X,
                floorRoute.OffsetEnd.Y - floorRoute.StubEnd.Y,
                floorRoute.OffsetEnd.Z - floorRoute.StubEnd.Z)
                - 45) < 0.000001,
            "floor first elbow is 45 degrees");
        Expect(
            floorRoute.StubEnd.Z >= floorRoute.OffsetEnd.Z
                && floorRoute.OffsetEnd.Z >= floorRoute.MainTie.Z,
            "floor double 45 monotonic");
        Expect(
            Math.Abs(DrainageEngineeringCore.AxialAngleDegrees(
                floorRoute.OffsetEnd.X - floorRoute.StubEnd.X,
                floorRoute.OffsetEnd.Y - floorRoute.StubEnd.Y,
                floorRoute.OffsetEnd.Z - floorRoute.StubEnd.Z,
                floorRoute.MainTie.X - floorRoute.OffsetEnd.X,
                floorRoute.MainTie.Y - floorRoute.OffsetEnd.Y,
                floorRoute.MainTie.Z - floorRoute.OffsetEnd.Z)
                - 45) < 0.000001,
            "floor second elbow is 45 degrees");
        double floorTerminalHorizontal = Math.Sqrt(
            Math.Pow(
                floorRoute.MainTie.X - floorRoute.OffsetEnd.X,
                2)
            + Math.Pow(
                floorRoute.MainTie.Y - floorRoute.OffsetEnd.Y,
                2));
        Expect(
            Math.Abs((
                floorRoute.OffsetEnd.Z - floorRoute.MainTie.Z)
                / floorTerminalHorizontal
                - wallInput.SlopeRatio) < 0.000001,
            "floor terminal signed slope is one percent");
        Expect(
            floorRoute.OutletAdvance - wallInput.ElbowTakeout
                    >= wallInput.MinimumTangentLength
                && floorRoute.DiagonalTangentLength
                    >= wallInput.MinimumTangentLength
                && floorRoute.BranchTangentLength
                    >= wallInput.MinimumTangentLength,
            "floor three tangents respect minimum");
        double constrainedLateralLimit =
            floorRoute.MiddleLateralOffset * 0.75;
        wallInput.MaximumDouble45LateralOffset =
            constrainedLateralLimit;
        DrainageWallRouteSolution constrainedFloorRoute =
            DrainageEngineeringCore
                .SolveWallOutletGeneralDoubleFortyFive(wallInput);
        Expect(
            (constrainedFloorRoute.IsFeasible
                && constrainedFloorRoute.MiddleLateralOffset
                    <= constrainedLateralLimit + 0.000001)
                || (!constrainedFloorRoute.IsFeasible
                    && constrainedFloorRoute.FailureCode
                        == "DOUBLE45_OUT_OF_PLANE_LIMIT"),
            "floor solver honors lateral offset limit");
        wallInput.MaximumDouble45LateralOffset = null;
        DrainageGeometryPoint originalMainStart = wallInput.MainStart;
        DrainageGeometryPoint originalMainEnd = wallInput.MainEnd;
        wallInput.MainStart = originalMainEnd;
        wallInput.MainEnd = originalMainStart;
        wallInput.DownstreamEndpointIndex = 0;
        DrainageWallRouteSolution reversedFloor =
            DrainageEngineeringCore
                .SolveWallOutletGeneralDoubleFortyFive(wallInput);
        Expect(
            reversedFloor.IsFeasible
                && Math.Abs(
                    reversedFloor.MainTie.X
                    - floorRoute.MainTie.X) < 0.000001
                && Math.Abs(
                    reversedFloor.MainTie.Y
                    - floorRoute.MainTie.Y) < 0.000001,
            "floor endpoint reversal preserves downstream route");
        wallInput.MainStart = originalMainStart;
        wallInput.MainEnd = originalMainEnd;
        wallInput.DownstreamEndpointIndex = 1;
        wallInput.ElbowTakeout = 5000;
        Expect(
            !DrainageEngineeringCore
                .SolveWallOutletGeneralDoubleFortyFive(wallInput)
                .IsFeasible,
            "floor oversized takeout is blocked");
        wallInput.ElbowTakeout = 20;
        wallInput.OutletY = 1;
        wallInput.OutletZ = 0;
        wallInput.SearchStep = 10000;
        Expect(
            DrainageEngineeringCore
                .SolveWallOutletGeneralDoubleFortyFive(wallInput)
                .IsFeasible,
            "general wall route does not depend on sampling step");
        wallInput.MinimumTangentLength = 10000;
        Expect(
            DrainageEngineeringCore
                .SolveWallOutletGeneralDoubleFortyFive(wallInput)
                .FailureCode == "DOUBLE_45_TANGENT_TOO_SHORT",
            "general wall continuous interval rejects impossible tangent");
        Expect(
            Math.Abs(DrainageEngineeringCore.SegmentDistance3D(
                new DrainageGeometryPoint { X = -1, Y = 0, Z = 0 },
                new DrainageGeometryPoint { X = 1, Y = 0, Z = 0 },
                new DrainageGeometryPoint { X = 0, Y = -1, Z = 0 },
                new DrainageGeometryPoint { X = 0, Y = 1, Z = 0 }))
                < 0.000001,
            "crossing segments collide");
        Expect(
            Math.Abs(DrainageEngineeringCore.SegmentDistance3D(
                new DrainageGeometryPoint { X = 0, Y = 0, Z = 0 },
                new DrainageGeometryPoint { X = 1, Y = 0, Z = 0 },
                new DrainageGeometryPoint { X = 0, Y = 2, Z = 0 },
                new DrainageGeometryPoint { X = 1, Y = 2, Z = 0 }) - 2)
                < 0.000001,
            "parallel segment clearance");
        Expect(
            Math.Abs(DrainageEngineeringCore.SegmentDistance3D(
                new DrainageGeometryPoint { X = 0, Y = 0, Z = 0 },
                new DrainageGeometryPoint { X = 0, Y = 0, Z = 0 },
                new DrainageGeometryPoint { X = 0, Y = 0, Z = 3 },
                new DrainageGeometryPoint { X = 0, Y = 0, Z = 3 }) - 3)
                < 0.000001,
            "degenerate segment clearance");
        Expect(
            DrainageEngineeringCore.AreJunctionDiametersCompatible(
                100,
                100,
                75,
                100,
                75,
                1),
            "reducing junction accepts 100x75");
        Expect(
            !DrainageEngineeringCore.AreJunctionDiametersCompatible(
                100,
                100,
                100,
                100,
                75,
                1),
            "reducing junction rejects wrong branch size");
        double projectedElevation;
        double projectedParameter;
        Expect(
            DrainageEngineeringCore.TryProjectPlanElevation(
                new DrainageGeometryPoint { X = 0, Y = 0, Z = 10 },
                new DrainageGeometryPoint { X = 10, Y = 0, Z = 9 },
                new DrainageGeometryPoint { X = 5, Y = 3, Z = 0 },
                out projectedElevation,
                out projectedParameter)
            && Math.Abs(projectedElevation - 9.5) < 0.000001
            && Math.Abs(projectedParameter - 0.5) < 0.000001,
            "plan projection reads local sloped centerline elevation");
        Expect(
            DrainageEngineeringCore.IsDownwardVerticalDisplacement(
                0.5,
                0.5,
                -100,
                1,
                50),
            "vertical down accepts bounded plan offset");
        Expect(
            !DrainageEngineeringCore.IsDownwardVerticalDisplacement(
                2,
                0,
                -100,
                1,
                50),
            "vertical down rejects lateral offset");
        Expect(
            DrainageEngineeringCore.IsDownwardFortyFiveDisplacement(
                100,
                0,
                -100,
                1,
                50),
            "down 45 accepts equal run and drop");
        Expect(
            !DrainageEngineeringCore.IsDownwardFortyFiveDisplacement(
                200,
                0,
                -100,
                1,
                50),
            "down 45 rejects wrong angle");
        Console.WriteLine(_failures == 0 ? "PASS: 100 drainage engineering core tests" : "FAILED");
        return _failures == 0 ? 0 : 1;
    }
}
