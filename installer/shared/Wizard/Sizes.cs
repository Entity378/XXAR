namespace XXAR.Wizard
{
    // Byte counts as a person would read them.
    public static class Sizes
    {
        private static readonly string[] Units = { "bytes", "KB", "MB", "GB" };

        public static string Describe(long bytes)
        {
            if (bytes <= 0) return "empty";

            double value = bytes;
            int unit = 0;
            while (value >= 1024 && unit < Units.Length - 1)
            {
                value /= 1024;
                unit++;
            }
            return unit == 0 ? $"{value:N0} {Units[unit]}" : $"{value:N1} {Units[unit]}";
        }
    }
}
