using System;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using XXAR.Uninstall.Steps;
using XXAR.Wizard;

namespace XXAR.Uninstall
{
    // Holds the plan and shows one step at a time; the steps decide among themselves what comes next.
    public partial class MainWindow : Window
    {
        public RemovalPlan Plan { get; }

        public MainWindow(RemovalPlan plan)
        {
            Plan = plan;
            InitializeComponent();
            SourceInitialized += (sender, e) => UseDarkTitleBar();

            Show(plan.IsInstalled
                ? (object)new ChoicesStep(this)
                : new FinishStep(this, FinishOutcome.NothingToDo));
        }

        public void Show(object step)
        {
            StepHost.Content = step;
        }

        public void Close(int exitCode)
        {
            base.Close();
            Application.Current.Shutdown(exitCode);
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
