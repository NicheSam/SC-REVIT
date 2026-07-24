using System;
using System.Collections.Generic;
using System.Linq;

namespace RfaMetadataAddin.Drainage
{
    internal sealed class DrainageDoubleFortyFiveSolution
    {
        public bool IsFeasible { get; set; }
        public string FailureCode { get; set; }
        public double ElevationOffset { get; set; }
        public double RunAdvance { get; set; }
        public double CenterlineDiagonalLength { get; set; }
        public double TangentLength { get; set; }
    }

    internal sealed class DrainageGeometryPoint
    {
        public double X { get; set; }
        public double Y { get; set; }
        public double Z { get; set; }
    }

    internal sealed class DrainageWallRouteInput
    {
        public DrainageGeometryPoint Source { get; set; }
        public double OutletX { get; set; }
        public double OutletY { get; set; }
        public double OutletZ { get; set; }
        public DrainageGeometryPoint MainStart { get; set; }
        public DrainageGeometryPoint MainEnd { get; set; }
        public int DownstreamEndpointIndex { get; set; }
        public double SlopeRatio { get; set; }
        public double StubLength { get; set; }
        public double ElbowTakeout { get; set; }
        public double JunctionBranchTakeout { get; set; }
        public double MinimumTangentLength { get; set; }
        public double MainEndClearance { get; set; }
        public double MaximumOutletAdvance { get; set; }
        public double? MaximumDouble45LateralOffset { get; set; }
        public double SearchStep { get; set; }
    }

    internal sealed class DrainageWallRouteSolution
    {
        public bool IsFeasible { get; set; }
        public string FailureCode { get; set; }
        public DrainageGeometryPoint StubEnd { get; set; }
        public DrainageGeometryPoint OffsetEnd { get; set; }
        public DrainageGeometryPoint BranchStart { get; set; }
        public DrainageGeometryPoint MainTie { get; set; }
        public double VerticalOffset { get; set; }
        public double DiagonalTangentLength { get; set; }
        public double PostOffsetTangentLength { get; set; }
        public double BranchTangentLength { get; set; }
        public double PlanTurnAngleDegrees { get; set; }
        public int SideSign { get; set; }
        public double OutletAdvance { get; set; }
        public double MiddleLateralOffset { get; set; }
    }

    internal static class DrainageEngineeringCore
    {
        // Endpoint order is geometry storage, not drainage semantics. Flat or
        // ambiguous mains therefore require an explicit downstream choice.
        public static int ResolveDownstreamEndpoint(
            double startZ,
            double endZ,
            double horizontalLength,
            string downstreamMode,
            double minimumDetectableSlope)
        {
            if (downstreamMode == "end0")
            {
                return 0;
            }
            if (downstreamMode == "end1")
            {
                return 1;
            }
            if (horizontalLength <= 0)
            {
                return -1;
            }
            double signedSlope = (startZ - endZ) / horizontalLength;
            if (Math.Abs(signedSlope) < minimumDetectableSlope)
            {
                return -1;
            }
            return startZ < endZ ? 0 : 1;
        }

        public static double ComputeSignedSlope(
            double sourceZ,
            double sinkZ,
            double horizontalLength)
        {
            return horizontalLength > 0
                ? (sourceZ - sinkZ) / horizontalLength
                : double.NaN;
        }

        public static bool IsExpectedDescendingSlope(
            double sourceZ,
            double sinkZ,
            double horizontalLength,
            double expectedSlope,
            double tolerance)
        {
            double actual = ComputeSignedSlope(sourceZ, sinkZ, horizontalLength);
            return !double.IsNaN(actual)
                && actual > 0
                && Math.Abs(actual - expectedSlope) <= tolerance;
        }

        public static string ClassifyConnectorAxis(double x, double y, double z)
        {
            // Revit connector orientation must be validated for usable family content.
            // Source: https://help.autodesk.com/cloudhelp/2024/ENU/Revit-Customize/files/GUID-4CEA251D-6898-471B-B6E1-84EA00608020.htm
            double length = Math.Sqrt(x * x + y * y + z * z);
            if (length <= 0.000001)
            {
                return "unknown";
            }
            double normalizedZ = Math.Abs(z / length);
            double normalizedHorizontal = Math.Sqrt(x * x + y * y) / length;
            if (normalizedZ >= 0.707)
            {
                return "vertical";
            }
            if (normalizedHorizontal >= 0.707)
            {
                return "horizontal";
            }
            return "unknown";
        }

        public static bool IsDownwardConnectorAxis(double x, double y, double z)
        {
            double length = Math.Sqrt(x * x + y * y + z * z);
            return length > 0.000001 && z / length <= -0.707;
        }

        public static bool IsConnectorAxisDirectedTowardTarget(
            double axisX,
            double axisY,
            double targetX,
            double targetY,
            double minimumDot)
        {
            double axisLength = Math.Sqrt(axisX * axisX + axisY * axisY);
            double targetLength = Math.Sqrt(targetX * targetX + targetY * targetY);
            if (axisLength <= 0.000001 || targetLength <= 0.000001)
            {
                return false;
            }
            double dot = (axisX * targetX + axisY * targetY)
                / (axisLength * targetLength);
            return dot > minimumDot;
        }

        public static bool IsAxisDirectedTowardTarget3D(
            double axisX,
            double axisY,
            double axisZ,
            double targetX,
            double targetY,
            double targetZ,
            double minimumDot)
        {
            double axisLength = Math.Sqrt(
                axisX * axisX + axisY * axisY + axisZ * axisZ);
            double targetLength = Math.Sqrt(
                targetX * targetX + targetY * targetY + targetZ * targetZ);
            if (axisLength <= 0.000001 || targetLength <= 0.000001)
            {
                return false;
            }
            double dot = (
                axisX * targetX
                + axisY * targetY
                + axisZ * targetZ)
                / (axisLength * targetLength);
            return dot > minimumDot;
        }

        public static double ComputeConnectorStubLength(
            double diameter,
            double minimumLength,
            double diameterMultiplier)
        {
            if (diameter <= 0 || minimumLength <= 0 || diameterMultiplier <= 0)
            {
                return double.NaN;
            }
            return Math.Max(minimumLength, diameter * diameterMultiplier);
        }

        public static bool IsMonotonicDescending(
            IList<double> elevations,
            double tolerance)
        {
            if (elevations == null || elevations.Count < 2)
            {
                return false;
            }
            for (int index = 0; index < elevations.Count - 1; index++)
            {
                if (elevations[index + 1] > elevations[index] + tolerance)
                {
                    return false;
                }
            }
            return true;
        }

        public static double AngleBetween2D(
            double ax,
            double ay,
            double bx,
            double by)
        {
            double aLength = Math.Sqrt(ax * ax + ay * ay);
            double bLength = Math.Sqrt(bx * bx + by * by);
            if (aLength <= 0.000001 || bLength <= 0.000001)
            {
                return double.NaN;
            }
            double dot = (ax * bx + ay * by) / (aLength * bLength);
            dot = Math.Max(-1.0, Math.Min(1.0, dot));
            return Math.Acos(dot) * 180.0 / Math.PI;
        }

        public static bool IsSideEntryAngleAllowed(
            double actualDegrees,
            double expectedDegrees,
            double toleranceDegrees)
        {
            return !double.IsNaN(actualDegrees)
                && Math.Abs(actualDegrees - expectedDegrees) <= toleranceDegrees;
        }

        public static bool IsDirectedSideEntryAllowed(
            double branchFlowX,
            double branchFlowY,
            double downstreamFlowX,
            double downstreamFlowY,
            double expectedDegrees,
            double toleranceDegrees)
        {
            double branchLength = Math.Sqrt(
                branchFlowX * branchFlowX
                + branchFlowY * branchFlowY);
            double downstreamLength = Math.Sqrt(
                downstreamFlowX * downstreamFlowX
                + downstreamFlowY * downstreamFlowY);
            if (branchLength <= 0.000001
                || downstreamLength <= 0.000001)
            {
                return false;
            }
            double directedDot = (
                branchFlowX * downstreamFlowX
                + branchFlowY * downstreamFlowY)
                / (branchLength * downstreamLength);
            return directedDot > 0
                && IsSideEntryAngleAllowed(
                    AngleBetween2D(
                        branchFlowX,
                        branchFlowY,
                        downstreamFlowX,
                        downstreamFlowY),
                    expectedDegrees,
                    toleranceDegrees);
        }

        public static double AxialAngleDegrees(
            double ax,
            double ay,
            double az,
            double bx,
            double by,
            double bz)
        {
            double aLength = Math.Sqrt(ax * ax + ay * ay + az * az);
            double bLength = Math.Sqrt(bx * bx + by * by + bz * bz);
            if (aLength <= 0.000001 || bLength <= 0.000001)
            {
                return double.NaN;
            }
            double dot = (ax * bx + ay * by + az * bz) / (aLength * bLength);
            dot = Math.Max(-1.0, Math.Min(1.0, dot));
            double degrees = Math.Acos(dot) * 180.0 / Math.PI;
            return Math.Min(degrees, 180.0 - degrees);
        }

        public static double RadialElevationAngleDegrees(
            double mainX,
            double mainY,
            double branchX,
            double branchY,
            double branchZ)
        {
            double mainLength = Math.Sqrt(mainX * mainX + mainY * mainY);
            if (mainLength <= 0.000001)
            {
                return double.NaN;
            }
            double unitX = mainX / mainLength;
            double unitY = mainY / mainLength;
            double alongMain = branchX * unitX + branchY * unitY;
            double radialX = branchX - alongMain * unitX;
            double radialY = branchY - alongMain * unitY;
            double radialHorizontal = Math.Sqrt(radialX * radialX + radialY * radialY);
            if (radialHorizontal <= 0.000001 && Math.Abs(branchZ) <= 0.000001)
            {
                return double.NaN;
            }
            return Math.Atan2(branchZ, radialHorizontal) * 180.0 / Math.PI;
        }

        public static bool IsRadialElevationAllowed(
            double actualDegrees,
            double minimumDegrees,
            double maximumDegrees,
            double toleranceDegrees)
        {
            return !double.IsNaN(actualDegrees)
                && actualDegrees >= minimumDegrees - toleranceDegrees
                && actualDegrees <= maximumDegrees + toleranceDegrees;
        }

        public static double ComputeDownstreamShiftForFortyFive(double lateralOffset)
        {
            return Math.Abs(lateralOffset);
        }

        public static DrainageDoubleFortyFiveSolution SolveDoubleFortyFiveOffset(
            double elevationOffset,
            double availableRun,
            double firstFittingTakeout,
            double secondFittingTakeout,
            double minimumTangentLength)
        {
            var result = new DrainageDoubleFortyFiveSolution
            {
                IsFeasible = false,
                FailureCode = "",
                ElevationOffset = Math.Abs(elevationOffset)
            };
            if (result.ElevationOffset <= 0
                || availableRun <= 0
                || firstFittingTakeout < 0
                || secondFittingTakeout < 0
                || minimumTangentLength <= 0)
            {
                result.FailureCode = "DOUBLE_45_INPUT_INVALID";
                return result;
            }
            result.RunAdvance = result.ElevationOffset;
            result.CenterlineDiagonalLength =
                Math.Sqrt(2.0) * result.ElevationOffset;
            result.TangentLength = result.CenterlineDiagonalLength
                - firstFittingTakeout
                - secondFittingTakeout;
            if (availableRun + 0.000001 < result.RunAdvance)
            {
                result.FailureCode = "DOUBLE_45_INSUFFICIENT_RUN";
                return result;
            }
            if (result.TangentLength + 0.000001 < minimumTangentLength)
            {
                result.FailureCode = "DOUBLE_45_TANGENT_TOO_SHORT";
                return result;
            }
            result.IsFeasible = true;
            return result;
        }

        public static bool IsPipeSegmentLengthAllowed(
            double centerlineLength,
            double startFittingTakeout,
            double endFittingTakeout,
            double minimumTangentLength)
        {
            if (centerlineLength <= 0
                || startFittingTakeout < 0
                || endFittingTakeout < 0
                || minimumTangentLength <= 0)
            {
                return false;
            }
            double tangentLength = centerlineLength
                - startFittingTakeout
                - endFittingTakeout;
            return tangentLength + 0.000001 >= minimumTangentLength;
        }

        public static double SegmentDistance3D(
            DrainageGeometryPoint firstStart,
            DrainageGeometryPoint firstEnd,
            DrainageGeometryPoint secondStart,
            DrainageGeometryPoint secondEnd)
        {
            if (firstStart == null
                || firstEnd == null
                || secondStart == null
                || secondEnd == null)
            {
                return double.NaN;
            }
            double ux = firstEnd.X - firstStart.X;
            double uy = firstEnd.Y - firstStart.Y;
            double uz = firstEnd.Z - firstStart.Z;
            double vx = secondEnd.X - secondStart.X;
            double vy = secondEnd.Y - secondStart.Y;
            double vz = secondEnd.Z - secondStart.Z;
            double wx = firstStart.X - secondStart.X;
            double wy = firstStart.Y - secondStart.Y;
            double wz = firstStart.Z - secondStart.Z;
            double a = ux * ux + uy * uy + uz * uz;
            double b = ux * vx + uy * vy + uz * vz;
            double c = vx * vx + vy * vy + vz * vz;
            double d = ux * wx + uy * wy + uz * wz;
            double e = vx * wx + vy * wy + vz * wz;
            const double epsilon = 0.000000000001;
            double denominator = a * c - b * b;
            double sNumerator;
            double sDenominator = denominator;
            double tNumerator;
            double tDenominator = denominator;
            if (a <= epsilon && c <= epsilon)
            {
                return Math.Sqrt(wx * wx + wy * wy + wz * wz);
            }
            if (a <= epsilon)
            {
                sNumerator = 0;
                sDenominator = 1;
                tNumerator = e;
                tDenominator = c;
            }
            else if (c <= epsilon)
            {
                tNumerator = 0;
                tDenominator = 1;
                sNumerator = -d;
                sDenominator = a;
            }
            else
            {
                if (denominator <= epsilon)
                {
                    sNumerator = 0;
                    sDenominator = 1;
                    tNumerator = e;
                    tDenominator = c;
                }
                else
                {
                    sNumerator = b * e - c * d;
                    tNumerator = a * e - b * d;
                    if (sNumerator < 0)
                    {
                        sNumerator = 0;
                        tNumerator = e;
                        tDenominator = c;
                    }
                    else if (sNumerator > sDenominator)
                    {
                        sNumerator = sDenominator;
                        tNumerator = e + b;
                        tDenominator = c;
                    }
                }
                if (tNumerator < 0)
                {
                    tNumerator = 0;
                    if (-d < 0)
                    {
                        sNumerator = 0;
                    }
                    else if (-d > a)
                    {
                        sNumerator = sDenominator;
                    }
                    else
                    {
                        sNumerator = -d;
                        sDenominator = a;
                    }
                }
                else if (tNumerator > tDenominator)
                {
                    tNumerator = tDenominator;
                    if (-d + b < 0)
                    {
                        sNumerator = 0;
                    }
                    else if (-d + b > a)
                    {
                        sNumerator = sDenominator;
                    }
                    else
                    {
                        sNumerator = -d + b;
                        sDenominator = a;
                    }
                }
            }
            double sc = Math.Abs(sNumerator) <= epsilon
                ? 0
                : sNumerator / sDenominator;
            double tc = Math.Abs(tNumerator) <= epsilon
                ? 0
                : tNumerator / tDenominator;
            double dx = wx + sc * ux - tc * vx;
            double dy = wy + sc * uy - tc * vy;
            double dz = wz + sc * uz - tc * vz;
            return Math.Sqrt(dx * dx + dy * dy + dz * dz);
        }

        public static DrainageWallRouteSolution SolveWallOutletDoubleFortyFive(
            DrainageWallRouteInput input)
        {
            var noSolution = new DrainageWallRouteSolution
            {
                IsFeasible = false,
                FailureCode = "WALL_DOUBLE_45_INPUT_INVALID"
            };
            if (input == null
                || input.Source == null
                || input.MainStart == null
                || input.MainEnd == null
                || input.SlopeRatio <= 0
                || input.StubLength <= 0
                || input.StubLength <= 0
                || input.ElbowTakeout <= 0
                || input.JunctionBranchTakeout <= 0
                || input.MinimumTangentLength <= 0
                || input.MaximumOutletAdvance <= 0
                || input.MaximumOutletAdvance <= input.StubLength
                || input.SearchStep <= 0
                || (input.DownstreamEndpointIndex != 0
                    && input.DownstreamEndpointIndex != 1))
            {
                return noSolution;
            }
            double outletLength = Math.Sqrt(
                input.OutletX * input.OutletX
                + input.OutletY * input.OutletY);
            double mainX = input.MainEnd.X - input.MainStart.X;
            double mainY = input.MainEnd.Y - input.MainStart.Y;
            double mainLength = Math.Sqrt(mainX * mainX + mainY * mainY);
            if (outletLength <= 0.000001 || mainLength <= 0.000001)
            {
                return noSolution;
            }
            if (!IsPipeSegmentLengthAllowed(
                input.StubLength,
                0,
                input.ElbowTakeout,
                input.MinimumTangentLength))
            {
                noSolution.FailureCode = "WALL_STUB_TANGENT_TOO_SHORT";
                return noSolution;
            }
            double outletX = input.OutletX / outletLength;
            double outletY = input.OutletY / outletLength;
            double downstreamX = input.DownstreamEndpointIndex == 1
                ? mainX / mainLength
                : -mainX / mainLength;
            double downstreamY = input.DownstreamEndpointIndex == 1
                ? mainY / mainLength
                : -mainY / mainLength;
            double minimumMainParameter = input.MainEndClearance / mainLength;
            double maximumMainParameter = 1.0 - minimumMainParameter;
            DrainageWallRouteSolution best = null;
            bool hasSupportedPlanTurn = false;
            for (int sideSign = -1; sideSign <= 1; sideSign += 2)
            {
                double branchDirectionX = (
                    downstreamX - sideSign * downstreamY)
                    / Math.Sqrt(2.0);
                double branchDirectionY = (
                    downstreamY + sideSign * downstreamX)
                    / Math.Sqrt(2.0);
                double planTurn = AngleBetween2D(
                    outletX,
                    outletY,
                    branchDirectionX,
                    branchDirectionY);
                if (!IsSideEntryAngleAllowed(planTurn, 45, 3))
                {
                    continue;
                }
                hasSupportedPlanTurn = true;
                for (double advance = input.StubLength;
                    advance <= input.MaximumOutletAdvance + 0.000001;
                    advance += input.SearchStep)
                {
                    double branchStartX =
                        input.Source.X + outletX * advance;
                    double branchStartY =
                        input.Source.Y + outletY * advance;
                    double denominator = Cross2D(
                        branchDirectionX,
                        branchDirectionY,
                        mainX,
                        mainY);
                    if (Math.Abs(denominator) <= 0.000001)
                    {
                        break;
                    }
                    double fromBranchToMainX =
                        input.MainStart.X - branchStartX;
                    double fromBranchToMainY =
                        input.MainStart.Y - branchStartY;
                    double branchLength = Cross2D(
                        fromBranchToMainX,
                        fromBranchToMainY,
                        mainX,
                        mainY) / denominator;
                    double mainParameter = Cross2D(
                        fromBranchToMainX,
                        fromBranchToMainY,
                        branchDirectionX,
                        branchDirectionY) / denominator;
                    if (branchLength <= 0
                        || mainParameter < minimumMainParameter
                        || mainParameter > maximumMainParameter)
                    {
                        continue;
                    }
                    double tieZ = input.MainStart.Z
                        + (input.MainEnd.Z - input.MainStart.Z)
                        * mainParameter;
                    double branchStartZ =
                        tieZ + input.SlopeRatio * branchLength;
                    double verticalOffset =
                        input.Source.Z - branchStartZ;
                    if (verticalOffset <= 0)
                    {
                        continue;
                    }
                    DrainageDoubleFortyFiveSolution offset =
                        SolveDoubleFortyFiveOffset(
                            verticalOffset,
                            advance - input.StubLength,
                            input.ElbowTakeout,
                            input.ElbowTakeout,
                            input.MinimumTangentLength);
                    if (!offset.IsFeasible)
                    {
                        noSolution.FailureCode = offset.FailureCode;
                        continue;
                    }
                    double postOffsetLength =
                        advance - input.StubLength - verticalOffset;
                    if (!IsPipeSegmentLengthAllowed(
                        postOffsetLength,
                        input.ElbowTakeout,
                        input.ElbowTakeout,
                        input.MinimumTangentLength))
                    {
                        noSolution.FailureCode =
                            "WALL_POST_OFFSET_TANGENT_TOO_SHORT";
                        continue;
                    }
                    double branchCenterlineLength = Math.Sqrt(
                        branchLength * branchLength
                        + Math.Pow(
                            input.SlopeRatio * branchLength,
                            2));
                    if (!IsPipeSegmentLengthAllowed(
                        branchCenterlineLength,
                        input.ElbowTakeout,
                        input.JunctionBranchTakeout,
                        input.MinimumTangentLength))
                    {
                        noSolution.FailureCode =
                            "WALL_BRANCH_TANGENT_TOO_SHORT";
                        continue;
                    }
                    var candidate = new DrainageWallRouteSolution
                    {
                        IsFeasible = true,
                        FailureCode = "",
                        StubEnd = Point(
                            input.Source.X + outletX * input.StubLength,
                            input.Source.Y + outletY * input.StubLength,
                            input.Source.Z),
                        OffsetEnd = Point(
                            input.Source.X
                                + outletX
                                * (input.StubLength + verticalOffset),
                            input.Source.Y
                                + outletY
                                * (input.StubLength + verticalOffset),
                            branchStartZ),
                        BranchStart = Point(
                            branchStartX,
                            branchStartY,
                            branchStartZ),
                        MainTie = Point(
                            input.MainStart.X + mainX * mainParameter,
                            input.MainStart.Y + mainY * mainParameter,
                            tieZ),
                        VerticalOffset = verticalOffset,
                        DiagonalTangentLength = offset.TangentLength,
                        PostOffsetTangentLength = postOffsetLength
                            - 2.0 * input.ElbowTakeout,
                        BranchTangentLength = branchCenterlineLength
                            - input.ElbowTakeout
                            - input.JunctionBranchTakeout,
                        PlanTurnAngleDegrees = planTurn,
                        SideSign = sideSign,
                        OutletAdvance = advance
                    };
                    if (best == null
                        || candidate.OutletAdvance < best.OutletAdvance)
                    {
                        best = candidate;
                    }
                    break;
                }
            }
            if (!hasSupportedPlanTurn)
            {
                noSolution.FailureCode =
                    "WALL_PLAN_TURN_UNSUPPORTED";
            }
            return best ?? noSolution;
        }

        public static DrainageWallRouteSolution
            SolveWallOutletGeneralDoubleFortyFive(
                DrainageWallRouteInput input)
        {
            var noSolution = new DrainageWallRouteSolution
            {
                IsFeasible = false,
                FailureCode = "WALL_DOUBLE_45_INPUT_INVALID"
            };
            if (input == null
                || input.Source == null
                || input.MainStart == null
                || input.MainEnd == null
                || input.SlopeRatio <= 0
                || input.ElbowTakeout <= 0
                || input.JunctionBranchTakeout <= 0
                || input.MinimumTangentLength <= 0
                || input.MaximumOutletAdvance <= input.StubLength
                || input.SearchStep <= 0
                || (input.DownstreamEndpointIndex != 0
                    && input.DownstreamEndpointIndex != 1))
            {
                return noSolution;
            }
            DrainageVector3 outlet = NormalizeVector(new DrainageVector3(
                input.OutletX,
                input.OutletY,
                input.OutletZ));
            DrainageVector3 main = new DrainageVector3(
                input.MainEnd.X - input.MainStart.X,
                input.MainEnd.Y - input.MainStart.Y,
                input.MainEnd.Z - input.MainStart.Z);
            double mainHorizontalLength = Math.Sqrt(
                main.X * main.X + main.Y * main.Y);
            if (outlet == null || mainHorizontalLength <= 0.000001)
            {
                return noSolution;
            }
            double downstreamX = input.DownstreamEndpointIndex == 1
                ? main.X / mainHorizontalLength
                : -main.X / mainHorizontalLength;
            double downstreamY = input.DownstreamEndpointIndex == 1
                ? main.Y / mainHorizontalLength
                : -main.Y / mainHorizontalLength;
            double minimumParameter =
                input.MainEndClearance / mainHorizontalLength;
            double maximumParameter = 1.0 - minimumParameter;
            if (minimumParameter >= maximumParameter)
            {
                noSolution.FailureCode = "MAIN_TIE_INTERVAL_EMPTY";
                return noSolution;
            }
            DrainageWallRouteSolution best = null;
            double bestMargin = double.NegativeInfinity;
            double bestTotalLength = double.PositiveInfinity;
            bool foundDirectionSolution = false;
            bool rejectedByLateralOffset = false;
            for (int sideSign = -1; sideSign <= 1; sideSign += 2)
            {
                double branchHorizontalX = (
                    downstreamX - sideSign * downstreamY)
                    / Math.Sqrt(2.0);
                double branchHorizontalY = (
                    downstreamY + sideSign * downstreamX)
                    / Math.Sqrt(2.0);
                DrainageVector3 terminal = NormalizeVector(
                    new DrainageVector3(
                        branchHorizontalX,
                        branchHorizontalY,
                        -input.SlopeRatio));
                if (terminal == null)
                {
                    continue;
                }
                IList<DrainageVector3> middleDirections =
                    SolveEqualAngleMiddleDirections(
                        outlet,
                        terminal,
                        45.0);
                foreach (DrainageVector3 middle in middleDirections)
                {
                    if (middle.Z >= -0.000001)
                    {
                        continue;
                    }
                    foundDirectionSolution = true;
                    double determinant = Dot(
                        outlet,
                        Cross(middle, terminal));
                    if (Math.Abs(determinant) <= 0.000001)
                    {
                        continue;
                    }
                    DrainageLengthCoefficients lengths =
                        ComputeDrainageLengthCoefficients(
                            input,
                            main,
                            outlet,
                            middle,
                            terminal,
                            determinant);
                    double feasibleMinimum = minimumParameter;
                    double feasibleMaximum = maximumParameter;
                    double minimumFirstLength = Math.Max(
                        input.StubLength,
                        input.ElbowTakeout
                            + input.MinimumTangentLength);
                    if (!ConstrainDrainageAffineAtLeast(
                            ref feasibleMinimum,
                            ref feasibleMaximum,
                            lengths.FirstAtZero,
                            lengths.FirstDelta,
                            minimumFirstLength)
                        || !ConstrainDrainageAffineAtMost(
                            ref feasibleMinimum,
                            ref feasibleMaximum,
                            lengths.FirstAtZero,
                            lengths.FirstDelta,
                            input.MaximumOutletAdvance)
                        || !ConstrainDrainageAffineAtLeast(
                            ref feasibleMinimum,
                            ref feasibleMaximum,
                            lengths.MiddleAtZero,
                            lengths.MiddleDelta,
                            2.0 * input.ElbowTakeout
                                + input.MinimumTangentLength)
                        || !ConstrainDrainageAffineAtLeast(
                            ref feasibleMinimum,
                            ref feasibleMaximum,
                            lengths.TerminalAtZero,
                            lengths.TerminalDelta,
                            input.ElbowTakeout
                                + input.JunctionBranchTakeout
                                + input.MinimumTangentLength))
                    {
                        noSolution.FailureCode =
                            "DOUBLE_45_TANGENT_TOO_SHORT";
                        continue;
                    }
                    var candidateParameters = new List<double>();
                    AddDrainageCandidateParameter(
                        candidateParameters,
                        feasibleMinimum,
                        feasibleMinimum,
                        feasibleMaximum);
                    AddDrainageCandidateParameter(
                        candidateParameters,
                        feasibleMaximum,
                        feasibleMinimum,
                        feasibleMaximum);
                    AddDrainageCandidateParameter(
                        candidateParameters,
                        ProjectDrainageParameterToMain(
                            input.Source,
                            input.MainStart,
                            main),
                        feasibleMinimum,
                        feasibleMaximum);
                    AddDrainageMarginIntersection(
                        candidateParameters,
                        lengths.FirstAtZero - input.ElbowTakeout,
                        lengths.FirstDelta,
                        lengths.MiddleAtZero
                            - 2.0 * input.ElbowTakeout,
                        lengths.MiddleDelta,
                        feasibleMinimum,
                        feasibleMaximum);
                    AddDrainageMarginIntersection(
                        candidateParameters,
                        lengths.FirstAtZero - input.ElbowTakeout,
                        lengths.FirstDelta,
                        lengths.TerminalAtZero
                            - input.ElbowTakeout
                            - input.JunctionBranchTakeout,
                        lengths.TerminalDelta,
                        feasibleMinimum,
                        feasibleMaximum);
                    AddDrainageMarginIntersection(
                        candidateParameters,
                        lengths.MiddleAtZero
                            - 2.0 * input.ElbowTakeout,
                        lengths.MiddleDelta,
                        lengths.TerminalAtZero
                            - input.ElbowTakeout
                            - input.JunctionBranchTakeout,
                        lengths.TerminalDelta,
                        feasibleMinimum,
                        feasibleMaximum);
                    foreach (double parameter in candidateParameters)
                    {
                        double firstLength =
                            lengths.FirstAtZero
                            + lengths.FirstDelta * parameter;
                        double middleLength =
                            lengths.MiddleAtZero
                            + lengths.MiddleDelta * parameter;
                        double terminalLength =
                            lengths.TerminalAtZero
                            + lengths.TerminalDelta * parameter;
                        double totalLength =
                            firstLength + middleLength + terminalLength;
                        double firstTangent = firstLength
                            - input.ElbowTakeout;
                        double middleTangent = middleLength
                            - 2.0 * input.ElbowTakeout;
                        double terminalTangent = terminalLength
                            - input.ElbowTakeout
                            - input.JunctionBranchTakeout;
                        double minimumMargin = Math.Min(
                            firstTangent,
                            Math.Min(middleTangent, terminalTangent))
                            - input.MinimumTangentLength;
                        if (minimumMargin < -0.000001)
                        {
                            noSolution.FailureCode =
                                "DOUBLE_45_TANGENT_TOO_SHORT";
                            continue;
                        }
                        DrainageGeometryPoint tie = Point(
                            input.MainStart.X + main.X * parameter,
                            input.MainStart.Y + main.Y * parameter,
                            input.MainStart.Z + main.Z * parameter);
                        DrainageGeometryPoint vertex1 = AddScaled(
                            input.Source,
                            outlet,
                            firstLength);
                        DrainageGeometryPoint vertex2 = AddScaled(
                            vertex1,
                            middle,
                            middleLength);
                        double middleLateralOffset = 0;
                        DrainageVector3 routePlaneNormal = NormalizeVector(
                            Cross(outlet, terminal));
                        if (routePlaneNormal != null)
                        {
                            middleLateralOffset = Math.Abs(
                                Dot(middle, routePlaneNormal)
                                    * middleLength);
                        }
                        if (input.MaximumDouble45LateralOffset.HasValue
                            && middleLateralOffset
                                > input.MaximumDouble45LateralOffset.Value
                                    + 0.000001)
                        {
                            rejectedByLateralOffset = true;
                            continue;
                        }
                        if (vertex1.Z
                                > input.Source.Z + 0.000001
                            || vertex2.Z
                                > vertex1.Z + 0.000001
                            || tie.Z
                                > vertex2.Z + 0.000001)
                        {
                            noSolution.FailureCode = "LOCAL_RISE";
                            continue;
                        }
                        if (best == null
                            || minimumMargin > bestMargin + 0.000001
                            || (Math.Abs(minimumMargin - bestMargin)
                                    <= 0.000001
                                && totalLength < bestTotalLength))
                        {
                            bestMargin = minimumMargin;
                            bestTotalLength = totalLength;
                            best = new DrainageWallRouteSolution
                            {
                                IsFeasible = true,
                                FailureCode = "",
                                StubEnd = vertex1,
                                OffsetEnd = vertex2,
                                BranchStart = vertex2,
                                MainTie = tie,
                                VerticalOffset =
                                    input.Source.Z - vertex2.Z,
                                DiagonalTangentLength = middleTangent,
                                PostOffsetTangentLength = 0,
                                BranchTangentLength = terminalTangent,
                                PlanTurnAngleDegrees = AngleBetween2D(
                                    outlet.X,
                                    outlet.Y,
                                    branchHorizontalX,
                                    branchHorizontalY),
                                SideSign = sideSign,
                                OutletAdvance = firstLength,
                                MiddleLateralOffset =
                                    middleLateralOffset
                            };
                        }
                    }
                }
            }
            if (best != null)
            {
                return best;
            }
            if (!foundDirectionSolution)
            {
                noSolution.FailureCode =
                    "DOUBLE_45_DIRECTION_NO_SOLUTION";
            }
            else if (rejectedByLateralOffset)
            {
                noSolution.FailureCode =
                    "DOUBLE45_OUT_OF_PLANE_LIMIT";
            }
            return noSolution;
        }

        private sealed class DrainageLengthCoefficients
        {
            public double FirstAtZero { get; set; }
            public double FirstDelta { get; set; }
            public double MiddleAtZero { get; set; }
            public double MiddleDelta { get; set; }
            public double TerminalAtZero { get; set; }
            public double TerminalDelta { get; set; }
        }

        private static DrainageLengthCoefficients
            ComputeDrainageLengthCoefficients(
                DrainageWallRouteInput input,
                DrainageVector3 main,
                DrainageVector3 outlet,
                DrainageVector3 middle,
                DrainageVector3 terminal,
                double determinant)
        {
            DrainageVector3 displacementAtZero = new DrainageVector3(
                input.MainStart.X - input.Source.X,
                input.MainStart.Y - input.Source.Y,
                input.MainStart.Z - input.Source.Z);
            DrainageVector3 middleCrossTerminal =
                Cross(middle, terminal);
            DrainageVector3 terminalCrossOutlet =
                Cross(terminal, outlet);
            DrainageVector3 outletCrossMiddle =
                Cross(outlet, middle);
            return new DrainageLengthCoefficients
            {
                FirstAtZero =
                    Dot(displacementAtZero, middleCrossTerminal)
                    / determinant,
                FirstDelta =
                    Dot(main, middleCrossTerminal) / determinant,
                MiddleAtZero =
                    Dot(displacementAtZero, terminalCrossOutlet)
                    / determinant,
                MiddleDelta =
                    Dot(main, terminalCrossOutlet) / determinant,
                TerminalAtZero =
                    Dot(displacementAtZero, outletCrossMiddle)
                    / determinant,
                TerminalDelta =
                    Dot(main, outletCrossMiddle) / determinant
            };
        }

        private static bool ConstrainDrainageAffineAtLeast(
            ref double minimumParameter,
            ref double maximumParameter,
            double valueAtZero,
            double delta,
            double minimumValue)
        {
            if (Math.Abs(delta) <= 0.000001)
            {
                return valueAtZero + 0.000001 >= minimumValue;
            }
            double boundary = (minimumValue - valueAtZero) / delta;
            if (delta > 0)
            {
                minimumParameter = Math.Max(
                    minimumParameter,
                    boundary);
            }
            else
            {
                maximumParameter = Math.Min(
                    maximumParameter,
                    boundary);
            }
            return minimumParameter <= maximumParameter + 0.000001;
        }

        private static bool ConstrainDrainageAffineAtMost(
            ref double minimumParameter,
            ref double maximumParameter,
            double valueAtZero,
            double delta,
            double maximumValue)
        {
            if (Math.Abs(delta) <= 0.000001)
            {
                return valueAtZero <= maximumValue + 0.000001;
            }
            double boundary = (maximumValue - valueAtZero) / delta;
            if (delta > 0)
            {
                maximumParameter = Math.Min(
                    maximumParameter,
                    boundary);
            }
            else
            {
                minimumParameter = Math.Max(
                    minimumParameter,
                    boundary);
            }
            return minimumParameter <= maximumParameter + 0.000001;
        }

        private static double ProjectDrainageParameterToMain(
            DrainageGeometryPoint point,
            DrainageGeometryPoint mainStart,
            DrainageVector3 main)
        {
            double lengthSquared = Dot(main, main);
            if (lengthSquared <= 0.000001)
            {
                return 0;
            }
            return (
                (point.X - mainStart.X) * main.X
                + (point.Y - mainStart.Y) * main.Y
                + (point.Z - mainStart.Z) * main.Z)
                / lengthSquared;
        }

        private static void AddDrainageMarginIntersection(
            IList<double> candidates,
            double firstAtZero,
            double firstDelta,
            double secondAtZero,
            double secondDelta,
            double minimumParameter,
            double maximumParameter)
        {
            double denominator = firstDelta - secondDelta;
            if (Math.Abs(denominator) <= 0.000001)
            {
                return;
            }
            AddDrainageCandidateParameter(
                candidates,
                (secondAtZero - firstAtZero) / denominator,
                minimumParameter,
                maximumParameter);
        }

        private static void AddDrainageCandidateParameter(
            IList<double> candidates,
            double parameter,
            double minimumParameter,
            double maximumParameter)
        {
            double clamped = Math.Max(
                minimumParameter,
                Math.Min(maximumParameter, parameter));
            if (!candidates.Any(
                item => Math.Abs(item - clamped) <= 0.0000001))
            {
                candidates.Add(clamped);
            }
        }

        private sealed class DrainageVector3
        {
            public DrainageVector3(double x, double y, double z)
            {
                X = x;
                Y = y;
                Z = z;
            }

            public double X { get; private set; }
            public double Y { get; private set; }
            public double Z { get; private set; }
        }

        private static IList<DrainageVector3> SolveEqualAngleMiddleDirections(
            DrainageVector3 incoming,
            DrainageVector3 outgoing,
            double angleDegrees)
        {
            var result = new List<DrainageVector3>();
            double cosine = Math.Cos(angleDegrees * Math.PI / 180.0);
            double gamma = Dot(incoming, outgoing);
            double denominator = 1.0 - gamma * gamma;
            if (Math.Abs(denominator) <= 0.000001)
            {
                return result;
            }
            double coefficientA =
                (cosine - gamma * cosine) / denominator;
            double coefficientB =
                (cosine - gamma * cosine) / denominator;
            DrainageVector3 baseVector = new DrainageVector3(
                coefficientA * incoming.X + coefficientB * outgoing.X,
                coefficientA * incoming.Y + coefficientB * outgoing.Y,
                coefficientA * incoming.Z + coefficientB * outgoing.Z);
            double heightSquared = 1.0 - Dot(baseVector, baseVector);
            if (heightSquared < -0.000001)
            {
                return result;
            }
            heightSquared = Math.Max(0, heightSquared);
            DrainageVector3 normal = NormalizeVector(
                Cross(incoming, outgoing));
            if (normal == null)
            {
                return result;
            }
            double height = Math.Sqrt(heightSquared);
            DrainageVector3 first = NormalizeVector(new DrainageVector3(
                baseVector.X + height * normal.X,
                baseVector.Y + height * normal.Y,
                baseVector.Z + height * normal.Z));
            DrainageVector3 second = NormalizeVector(new DrainageVector3(
                baseVector.X - height * normal.X,
                baseVector.Y - height * normal.Y,
                baseVector.Z - height * normal.Z));
            if (first != null)
            {
                result.Add(first);
            }
            if (second != null)
            {
                result.Add(second);
            }
            return result;
        }

        private static DrainageVector3 NormalizeVector(
            DrainageVector3 vector)
        {
            double length = Math.Sqrt(Dot(vector, vector));
            return length <= 0.000001
                ? null
                : new DrainageVector3(
                    vector.X / length,
                    vector.Y / length,
                    vector.Z / length);
        }

        private static double Dot(
            DrainageVector3 first,
            DrainageVector3 second)
        {
            return first.X * second.X
                + first.Y * second.Y
                + first.Z * second.Z;
        }

        private static DrainageVector3 Cross(
            DrainageVector3 first,
            DrainageVector3 second)
        {
            return new DrainageVector3(
                first.Y * second.Z - first.Z * second.Y,
                first.Z * second.X - first.X * second.Z,
                first.X * second.Y - first.Y * second.X);
        }

        private static DrainageGeometryPoint AddScaled(
            DrainageGeometryPoint point,
            DrainageVector3 direction,
            double length)
        {
            return Point(
                point.X + direction.X * length,
                point.Y + direction.Y * length,
                point.Z + direction.Z * length);
        }

        private static double Cross2D(
            double ax,
            double ay,
            double bx,
            double by)
        {
            return ax * by - ay * bx;
        }

        private static DrainageGeometryPoint Point(
            double x,
            double y,
            double z)
        {
            return new DrainageGeometryPoint { X = x, Y = y, Z = z };
        }
    }
}
