import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { useMe } from "@/hooks/useMe";
import { Calendar } from "@/routes/Calendar";
import { Home } from "@/routes/Home";
import { Login } from "@/routes/Login";
import { MinuteDetail } from "@/routes/MinuteDetail";
import { Minutes } from "@/routes/Minutes";
import { Profile } from "@/routes/Profile";
import { Projects } from "@/routes/Projects";
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
        <Route path="projects" element={<Projects />} />
        <Route path="profile" element={<Profile />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

export default App;
