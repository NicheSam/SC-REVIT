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
        Expect(DrainageEngineeringCore.IsExpectedDescendingSlope(10, 9, 100, 0.01, 0.000001), "one percent");
        Expect(!DrainageEngineeringCore.IsExpectedDescendingSlope(9, 10, 100, 0.01, 0.000001), "reverse fails");
        Expect(DrainageEngineeringCore.ClassifyConnectorAxis(0, 0, -1) == "vertical", "floor outlet");
        Expect(DrainageEngineeringCore.ClassifyConnectorAxis(1, 0, 0) == "horizontal", "wall outlet");
        Expect(DrainageEngineeringCore.IsDownwardConnectorAxis(0, 0, -1), "downward outlet");
        Expect(!DrainageEngineeringCore.IsDownwardConnectorAxis(0, 0, 1), "upward outlet rejected");
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
            floorRoute.MiddleLateralOffset > 0.000001
                && constrainedFloorRoute.IsFeasible
                && constrainedFloorRoute.MiddleLateralOffset
                    < floorRoute.MiddleLateralOffset
                && constrainedFloorRoute.MiddleLateralOffset
                    <= constrainedLateralLimit + 0.000001,
            "floor solver selects an in-limit alternative candidate");
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
        Console.WriteLine(_failures == 0 ? "PASS: 63 drainage engineering core tests" : "FAILED");
        return _failures == 0 ? 0 : 1;
    }
}
