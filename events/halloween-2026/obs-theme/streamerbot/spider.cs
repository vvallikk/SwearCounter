// EVENT: halloween-2026 — ВРЕМЕННО. Удалить вместе с папкой events/halloween-2026/obs-theme после 1 ноября 2026.
//
// Streamer.bot → Sub-Action «Core → C# → Execute C# Code».
// Выпускает пауков в spider.html. Режим берётся из аргумента %spiderMode%
// (run, swarm, drop, big), если его нет — обычная пробежка.
// Пример: награда за баллы канала «Выпустить паука» → это действие.
using System;

public class CPHInline
{
    public bool Execute()
    {
        string mode = args.ContainsKey("spiderMode") ? args["spiderMode"].ToString() : "run";
        int count = args.ContainsKey("spiderCount") ? Convert.ToInt32(args["spiderCount"]) : 12;
        CPH.WebsocketBroadcastJson("{\"overlay\":\"halloween\",\"action\":\"spider\",\"mode\":\"" + mode + "\",\"count\":" + count + "}");
        return true;
    }
}
