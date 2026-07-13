using System;
using System.IO;
using WixToolset.Dtf.WindowsInstaller;

namespace XXAR.Installer
{
    // Deferred custom actions the MSI runs, fed by CustomActionData from Setup.cs.
    // One cleans untracked runtime data on uninstall; the other normalizes the resources\ casing on upgrade.
    public static class CustomActions
    {
        [CustomAction]
        public static ActionResult CleanupXXARData(Session session)
        {
            var data = session.CustomActionData;
            // Local data is always under %LocalAppData%\XXAR regardless of the install dir; drop it wholesale.
            TryDeleteTree(data.ContainsKey("LOCAL_XXAR") ? data["LOCAL_XXAR"] : null);
            // MSI removes the Start Menu shortcut but can leave its now-empty folder behind; drop it too.
            TryDeleteTree(data.ContainsKey("STARTMENU_XXAR") ? data["STARTMENU_XXAR"] : null);
            // Roaming holds the mod library and settings; only remove it when the user opted in.
            if (data.ContainsKey("XXAR_PURGE_USERDATA") && data["XXAR_PURGE_USERDATA"] == "1")
                TryDeleteTree(data.ContainsKey("ROAMING_XXAR") ? data["ROAMING_XXAR"] : null);
            return ActionResult.Success;
        }

        // On install/upgrade, delete a wrongly-cased "Resources" folder so InstallFiles recreates it lowercase and flat.
        // The on-disk-name guard and the before-InstallFiles schedule keep it from touching a correct install or the new app.
        [CustomAction]
        public static ActionResult NormalizeResourcesCasing(Session session)
        {
            var data = session.CustomActionData;
            var installDir = data.ContainsKey("INSTALLDIR") ? data["INSTALLDIR"] : null;
            if (string.IsNullOrEmpty(installDir) || !Directory.Exists(installDir))
                return ActionResult.Success;
            try
            {
                foreach (var dir in Directory.GetDirectories(installDir))
                {
                    var name = Path.GetFileName(dir);
                    if (name.Equals("resources", StringComparison.OrdinalIgnoreCase) && name != "resources")
                        Directory.Delete(dir, true);
                }
            }
            catch
            {
                // Leave the old folder if something holds it; the app still runs (case-insensitive).
            }
            return ActionResult.Success;
        }

        private static void TryDeleteTree(string path)
        {
            try
            {
                if (!string.IsNullOrEmpty(path) && Directory.Exists(path))
                    Directory.Delete(path, true);
            }
            catch
            {
                // Never block an uninstall on a locked or held file.
            }
        }
    }
}
