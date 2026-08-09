using System;
using System.Diagnostics;

using XXAR.Wizard;

namespace XXAR.Setup
{
    // Removal of an older MSI install, so upgrading from the retired channel leaves nothing behind.
    public static class LegacyMsi
    {
        public static void RemoveIfPresent(IProgress<StepProgress> progress)
        {
            foreach (var productCode in InstallRecord.FindMsiProductCodes())
            {
                progress?.Report(new StepProgress(0, "Removing previous version..."));
                Journal.Info($"removing MSI product {productCode}");
                RunMsiExec(productCode);
            }
        }

        // UPGRADINGPRODUCTCODE suppresses the package's CleanupXXARData action, exactly as a real MSI
        // major upgrade would, so downloaded tools survive the migration.
        private static void RunMsiExec(string productCode)
        {
            var start = new ProcessStartInfo
            {
                FileName = InstallLocations.SystemExecutable("msiexec.exe"),
                Arguments = $"/x {productCode} /qn UPGRADINGPRODUCTCODE=1",
                UseShellExecute = false,
                CreateNoWindow = true,
            };

            using (var process = Process.Start(start))
            {
                process.WaitForExit();
                Journal.Info($"msiexec exit {process.ExitCode}");
            }
        }
    }
}
