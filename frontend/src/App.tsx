import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { useMe } from "@/hooks/useMe";
import { Calendar } from "@/routes/Calendar";
import { Home } from "@/routes/Home";
import { Login } from "@/routes/Login";
import { MinuteDetail } from "@/routes/MinuteDetail";
import { Minutes } from "@/routes/Minutes";
import { ProjectContext } from "@/routes/ProjectContext";
import { ProjectContextDetail } from "@/routes/ProjectContextDetail";
import { Profile } from "@/routes/Profile";
import { TicketDetail } from "@/routes/TicketDetail";
import { Tickets } from "@/routes/Tickets";

const App = () => {
  const me = useMe();

  if (me.isLoading) {
    return (
      <div className="grid h-full place-items-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (!me.data) {
    // 401 or any other error — show login
    return <Login />;
  }

  return (
    <Routes>
      <Route element={<AppShell user={me.data} />}>
        <Route index element={<Home />} />
        <Route path="calendar" element={<Calendar />} />
        <Route path="minutes" element={<Minutes />} />
        <Route path="minutes/:id" element={<MinuteDetail />} />
        <Route path="tickets" element={<Tickets />} />
        <Route path="tickets/:key" element={<TicketDetail />} />
        <Route path="project-context" element={<ProjectContext />} />
        <Route path="project-context/:id" element={<ProjectContextDetail />} />
        <Route path="profile" element={<Profile />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

export default App;
