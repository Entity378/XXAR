using System;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using XXAR.Setup.Steps;

using XXAR.Wizard;

namespace XXAR.Setup
{
    // Holds the session and shows one step at a time; the steps decide among themselves what comes next.
    public partial class MainWindow : Window
    {
        public SetupSession Session { get; }

        public MainWindow(SetupSession session)
        {
            Session = session;
            InitializeComponent();
            SourceInitialized += (sender, e) => UseDarkTitleBar();
            Show(FirstStep());
        }

        public void Show(object step)
        {
            StepHost.Content = step;
        }

        public void Abandon()
        {
            Close(1);
        }

        public void Close(int exitCode)
        {
            base.Close();
            Application.Current.Shutdown(exitCode);
        }

        private object FirstStep()
        {
            var machine = Session.Machine;

            // Nothing installed and nothing to install: offering "Uninstall" would be nonsense.
            if (Session.RemoveOnly && !machine.IsInstalled)
                return new FinishStep(this, FinishOutcome.NothingToDo, removing: true);

            if (Session.RemoveOnly)
                return new RemoveOptionsStep(this, allowBack: false);

            if (machine.IsSameVersionInstalled)
                return new MaintenanceStep(this);

            return new WelcomeStep(this);
        }

        private void UseDarkTitleBar()
        {
            try
            {
                var window = new WindowInteropHelper(this).Handle;
                int enabled = 1;
                DwmSetWindowAttribute(window, 20, ref enabled, sizeof(int));
            }
            catch (Exception ex)
            {
                Journal.Error("dark title bar unavailable", ex);
            }
        }

        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);
    }
}
