using System;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using XXAR.Setup.Pages;

namespace XXAR.Setup
{
    public partial class MainWindow : Window
    {
        public SetupContext Ctx { get; }

        public MainWindow(SetupContext ctx)
        {
            Ctx = ctx;
            InitializeComponent();
            SourceInitialized += (s, e) => EnableDarkTitleBar();

            // A payload-less stub with nothing installed has no job to do; offering "Uninstall" would be nonsense.
            if (Ctx.UninstallOnly && !Ctx.IsInstalled)
                Go(new ExitPage(this, ExitOutcome.NothingToDo, uninstalling: true));
            else if (Ctx.UninstallOnly)
                Go(new RemoveOptionsPage(this, allowBack: false));
            else if (Ctx.IsInstalled && Ctx.InstalledVersion == Ctx.PayloadVersion)
                Go(new MaintenancePage(this));
            else
                Go(new WelcomePage(this));
        }

        public void Go(object page) => PageHost.Content = page;

        public void CancelSetup()
        {
            Close();
            Application.Current.Shutdown(1);
        }

        public void FinishSetup(int exitCode)
        {
            Close();
            Application.Current.Shutdown(exitCode);
        }

        private void EnableDarkTitleBar()
        {
            try
            {
                var hwnd = new WindowInteropHelper(this).Handle;
                int enable = 1;
                DwmSetWindowAttribute(hwnd, 20, ref enable, sizeof(int));
            }
            catch { }
        }

        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);
    }
}
