using System;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace RfaMetadataAddin
{
    public static class ScIconFactory
    {
        private static readonly Color Cyan = Color.FromRgb(71, 183, 220);
        private static readonly Color White = Color.FromRgb(235, 242, 247);
        private static readonly Color Amber = Color.FromRgb(255, 177, 55);
        private static readonly Color Red = Color.FromRgb(235, 92, 92);
        private static readonly Color Green = Color.FromRgb(91, 201, 141);

        public static ImageSource Create(string iconName, int size)
        {
            DrawingVisual visual = new DrawingVisual();
            using (DrawingContext context = visual.RenderOpen())
            {
                Draw(context, iconName ?? string.Empty, size);
            }

            RenderTargetBitmap bitmap = new RenderTargetBitmap(
                size,
                size,
                96,
                96,
                PixelFormats.Pbgra32);
            bitmap.Render(visual);
            bitmap.Freeze();
            return bitmap;
        }

        private static void Draw(DrawingContext context, string name, int size)
        {
            double scale = size / 32.0;
            Pen cyan = Pen(Cyan, 2.1, scale);
            Pen white = Pen(White, 1.65, scale);
            Pen amber = Pen(Amber, 2.1, scale);
            Pen red = Pen(Red, 2.1, scale);
            Pen green = Pen(Green, 2.1, scale);

            context.DrawRectangle(
                Brushes.Transparent,
                null,
                new Rect(0, 0, size, size));

            if (name == "family_archive")
            {
                Box(context, white, cyan, scale);
                Arrow(context, amber, P(9, 25, scale), P(23, 25, scale), scale);
            }
            else if (name == "project_recovery")
            {
                Document(context, white, cyan, scale);
                ArcArrow(context, amber, P(24, 9, scale), P(25, 23, scale), scale);
            }
            else if (name == "point_placement")
            {
                Grid(context, white, scale);
                Crosshair(context, cyan, P(10, 11, scale), scale);
                Crosshair(context, cyan, P(21, 20, scale), scale);
                context.DrawEllipse(Brush(Amber), null, P(22, 10, scale), 2 * scale, 2 * scale);
            }
            else if (name == "backstage")
            {
                Document(context, white, cyan, scale);
                Gear(context, amber, P(23, 22, scale), scale);
            }
            else if (name == "fire_branch")
            {
                Pipe(context, red, P(5, 24, scale), P(27, 8, scale), scale);
                Pipe(context, cyan, P(15, 17, scale), P(8, 9, scale), scale);
                context.DrawEllipse(Brush(Red), null, P(8, 7, scale), 2.2 * scale, 2.2 * scale);
            }
            else if (name == "drainage_connect")
            {
                Pipe(context, cyan, P(5, 25, scale), P(27, 7, scale), scale);
                Pipe(context, amber, P(20, 13, scale), P(27, 25, scale), scale);
                Junction(context, green, P(20, 13, scale), scale);
            }
            else if (name == "drainage_settings")
            {
                Pipe(context, cyan, P(5, 22, scale), P(27, 10, scale), scale);
                Gear(context, amber, P(20, 21, scale), scale);
            }
            else if (name == "align_centerline")
            {
                Pipe(context, cyan, P(5, 9, scale), P(27, 9, scale), scale);
                Pipe(context, cyan, P(5, 23, scale), P(27, 23, scale), scale);
                context.DrawLine(white, P(4, 16, scale), P(28, 16, scale));
                Arrow(context, amber, P(10, 12, scale), P(10, 19, scale), scale);
                Arrow(context, amber, P(22, 20, scale), P(22, 13, scale), scale);
            }
            else if (name == "connect_45")
            {
                Pipe(context, cyan, P(4, 24, scale), P(12, 24, scale), scale);
                Pipe(context, amber, P(12, 24, scale), P(22, 14, scale), scale);
                Pipe(context, cyan, P(22, 14, scale), P(28, 14, scale), scale);
                Elbow(context, white, P(12, 24, scale), scale);
                Elbow(context, white, P(22, 14, scale), scale);
            }
            else if (name == "down_45")
            {
                Pipe(context, cyan, P(6, 7, scale), P(14, 15, scale), scale);
                Pipe(context, amber, P(14, 15, scale), P(25, 26, scale), scale);
                Arrow(context, white, P(22, 17, scale), P(22, 27, scale), scale);
            }
            else if (name == "vertical_down")
            {
                Pipe(context, cyan, P(16, 5, scale), P(16, 27, scale), scale);
                Arrow(context, amber, P(22, 11, scale), P(22, 27, scale), scale);
            }
            else if (name == "opening_locator")
            {
                context.DrawRectangle(null, white, R(6, 7, 20, 18, scale));
                Crosshair(context, cyan, P(16, 16, scale), scale);
                context.DrawEllipse(null, amber, P(16, 16, scale), 6 * scale, 6 * scale);
            }
            else if (name == "element_inspector")
            {
                Box(context, white, cyan, scale);
                Magnifier(context, amber, P(21, 21, scale), scale);
            }
            else if (name == "parameter_audit")
            {
                Document(context, white, cyan, scale);
                Check(context, green, P(20, 22, scale), scale);
            }
            else if (name == "breakpoint_check")
            {
                Pipe(context, cyan, P(4, 16, scale), P(12, 16, scale), scale);
                Pipe(context, cyan, P(20, 16, scale), P(28, 16, scale), scale);
                context.DrawEllipse(null, red, P(16, 16, scale), 4 * scale, 4 * scale);
                context.DrawLine(red, P(16, 11, scale), P(16, 17, scale));
                context.DrawEllipse(Brush(Red), null, P(16, 21, scale), 1.2 * scale, 1.2 * scale);
            }
            else if (name == "piping_support")
            {
                Pipe(context, cyan, P(4, 10, scale), P(28, 10, scale), scale);
                context.DrawLine(white, P(10, 12, scale), P(10, 24, scale));
                context.DrawLine(white, P(22, 12, scale), P(22, 24, scale));
                context.DrawLine(white, P(6, 24, scale), P(26, 24, scale));
                context.DrawEllipse(Brush(Amber), null, P(10, 17, scale), 2 * scale, 2 * scale);
                context.DrawEllipse(Brush(Amber), null, P(22, 17, scale), 2 * scale, 2 * scale);
            }
            else
            {
                Box(context, white, cyan, scale);
            }
        }

        private static Pen Pen(Color color, double width, double scale)
        {
            Pen pen = new Pen(Brush(color), width * scale);
            pen.StartLineCap = PenLineCap.Round;
            pen.EndLineCap = PenLineCap.Round;
            pen.LineJoin = PenLineJoin.Round;
            pen.Freeze();
            return pen;
        }

        private static SolidColorBrush Brush(Color color)
        {
            SolidColorBrush brush = new SolidColorBrush(color);
            brush.Freeze();
            return brush;
        }

        private static Point P(double x, double y, double scale)
        {
            return new Point(x * scale, y * scale);
        }

        private static Rect R(double x, double y, double width, double height, double scale)
        {
            return new Rect(x * scale, y * scale, width * scale, height * scale);
        }

        private static void Pipe(DrawingContext context, Pen pen, Point start, Point end, double scale)
        {
            context.DrawLine(Pen(White, 5.2, scale), start, end);
            context.DrawLine(pen, start, end);
        }

        private static void Grid(DrawingContext context, Pen pen, double scale)
        {
            context.DrawRectangle(null, pen, R(5, 5, 22, 22, scale));
            context.DrawLine(pen, P(16, 5, scale), P(16, 27, scale));
            context.DrawLine(pen, P(5, 16, scale), P(27, 16, scale));
        }

        private static void Crosshair(DrawingContext context, Pen pen, Point center, double scale)
        {
            context.DrawEllipse(null, pen, center, 4 * scale, 4 * scale);
            context.DrawLine(pen, P(center.X / scale - 6, center.Y / scale, scale), P(center.X / scale + 6, center.Y / scale, scale));
            context.DrawLine(pen, P(center.X / scale, center.Y / scale - 6, scale), P(center.X / scale, center.Y / scale + 6, scale));
        }

        private static void Junction(DrawingContext context, Pen pen, Point center, double scale)
        {
            context.DrawEllipse(Brush(Green), pen, center, 2.2 * scale, 2.2 * scale);
        }

        private static void Elbow(DrawingContext context, Pen pen, Point center, double scale)
        {
            context.DrawEllipse(Brush(Amber), pen, center, 2.1 * scale, 2.1 * scale);
        }

        private static void Arrow(DrawingContext context, Pen pen, Point start, Point end, double scale)
        {
            context.DrawLine(pen, start, end);
            Vector direction = start - end;
            direction.Normalize();
            Vector side = new Vector(-direction.Y, direction.X);
            Point left = end + direction * (4 * scale) + side * (3 * scale);
            Point right = end + direction * (4 * scale) - side * (3 * scale);
            context.DrawLine(pen, end, left);
            context.DrawLine(pen, end, right);
        }

        private static void Box(DrawingContext context, Pen white, Pen cyan, double scale)
        {
            context.DrawRectangle(null, white, R(6, 11, 20, 15, scale));
            context.DrawLine(cyan, P(6, 11, scale), P(12, 6, scale));
            context.DrawLine(cyan, P(26, 11, scale), P(20, 6, scale));
            context.DrawLine(cyan, P(12, 6, scale), P(20, 6, scale));
            context.DrawLine(cyan, P(16, 11, scale), P(16, 26, scale));
        }

        private static void Document(DrawingContext context, Pen white, Pen cyan, double scale)
        {
            context.DrawRectangle(null, white, R(7, 5, 15, 22, scale));
            context.DrawLine(cyan, P(10, 11, scale), P(19, 11, scale));
            context.DrawLine(cyan, P(10, 16, scale), P(19, 16, scale));
            context.DrawLine(cyan, P(10, 21, scale), P(16, 21, scale));
        }

        private static void Gear(DrawingContext context, Pen pen, Point center, double scale)
        {
            context.DrawEllipse(null, pen, center, 5 * scale, 5 * scale);
            context.DrawEllipse(null, pen, center, 1.8 * scale, 1.8 * scale);
            for (int index = 0; index < 8; index++)
            {
                double angle = Math.PI * index / 4.0;
                Vector radial = new Vector(Math.Cos(angle), Math.Sin(angle));
                context.DrawLine(
                    pen,
                    center + radial * (5 * scale),
                    center + radial * (7 * scale));
            }
        }

        private static void Magnifier(DrawingContext context, Pen pen, Point center, double scale)
        {
            context.DrawEllipse(null, pen, center, 5 * scale, 5 * scale);
            context.DrawLine(pen, center + new Vector(4, 4) * scale, center + new Vector(9, 9) * scale);
        }

        private static void Check(DrawingContext context, Pen pen, Point center, double scale)
        {
            context.DrawLine(pen, center + new Vector(-5, 0) * scale, center + new Vector(-1, 4) * scale);
            context.DrawLine(pen, center + new Vector(-1, 4) * scale, center + new Vector(7, -5) * scale);
        }

        private static void ArcArrow(DrawingContext context, Pen pen, Point start, Point end, double scale)
        {
            PathFigure figure = new PathFigure { StartPoint = start, IsClosed = false };
            figure.Segments.Add(new ArcSegment(
                end,
                new Size(8 * scale, 8 * scale),
                0,
                false,
                SweepDirection.Clockwise,
                true));
            PathGeometry geometry = new PathGeometry();
            geometry.Figures.Add(figure);
            context.DrawGeometry(null, pen, geometry);
            context.DrawLine(pen, end, end + new Vector(-4, -1) * scale);
            context.DrawLine(pen, end, end + new Vector(-1, -4) * scale);
        }
    }
}
