import json
import math
import os

# Set matplotlib backend for web rendering
if os.environ.get("WT_WEB_RENDER") == "1":
    import matplotlib

    matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.ticker import MultipleLocator

# If you really wanna bear all of this good luck lmao

output_dir = "top100_data"
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# My promo lol
author_tag = "Author's Twitter: @dokkan_wt_info"


def calculate_figsize(num_players, max_name_length):
    width = 10 + max(0, (max_name_length - 10) * 0.5)
    height = 6 + num_players * 0.2
    return (width, height)


def plot_and_save(
    players,
    key,
    xlabel,
    ylabel,
    title,
    output_dir,
    step=False,
    animate=False,
    multiple=False,
    border=None,
):
    if multiple:
        max_name_length = max(len(player["name"]) for player in players)
        figsize = calculate_figsize(len(players), max_name_length)

        fig, ax = plt.subplots(figsize=figsize)
        lines = []
        border_lines = []

        for player in players:
            player_name = player["name"].replace("$", "\$")
            (line,) = (
                ax.step(player["hour"], player[key], where="mid", label=player_name)
                if step
                else ax.plot(player["hour"], player[key], label=player_name)
            )
            lines.append(line)

        if border:
            for b in border:
                b_name = b["rank"]
                (border_line,) = ax.plot(
                    b["hour"], b[key], linestyle="dotted", label=f"{b_name} (border)"
                )
                border_lines.append(border_line)

        def update(num):
            for line, player in zip(lines, players):
                line.set_data(player["hour"][:num], player[key][:num])
            for border_line, b in zip(border_lines, border or []):
                border_line.set_data(b["hour"][:num], b[key][:num])
            return lines + border_lines

        if animate:
            ani = FuncAnimation(fig, update, frames=len(players[0]["hour"]), blit=True)
            plt.xlabel(xlabel)
            plt.ylabel(ylabel)
            plt.title(title)
            plt.grid(True)
            plt.legend(loc="center left", bbox_to_anchor=(1, 0.5))
            plt.text(
                0,
                -0.1,
                author_tag,
                transform=plt.gca().transAxes,
                ha="left",
                va="top",
                fontsize=10,
            )
            output_path = os.path.join(output_dir, f"multiple{key}.gif")
            ani.save(output_path, writer=PillowWriter(fps=10))
        else:
            plt.xlabel(xlabel)
            plt.ylabel(ylabel)
            plt.title(title)
            plt.grid(True)
            plt.legend(loc="center left", bbox_to_anchor=(1, 0.5))
            plt.text(
                0,
                -0.1,
                author_tag,
                transform=plt.gca().transAxes,
                ha="left",
                va="top",
                fontsize=10,
            )
            output_path = os.path.join(output_dir, f"multiple{key}.png")
            if step:
                plt.gca().invert_yaxis()
            plt.savefig(output_path, bbox_inches="tight")

        plt.close()

    else:
        for player in players:
            player_name = player["name"].replace("$", "\$")
            player_dir = os.path.join(output_dir, player_name)

            if not os.path.exists(player_dir):
                os.makedirs(player_dir)

            fig, ax = plt.subplots(figsize=(12, 6))
            (line,) = (
                ax.step(player["hour"], player[key], where="mid")
                if step
                else ax.plot(player["hour"], player[key])
            )

            if border:
                for b in border:
                    b_name = b["rank"]
                    ax.plot(
                        b["hour"],
                        b[key],
                        linestyle="dotted",
                        label=f"{b_name} (border)",
                    )

            plt.xlabel(xlabel)
            plt.ylabel(ylabel)
            plt.title(f"{player_name}'s {title}")
            plt.grid(True)
            plt.text(
                0,
                -0.1,
                author_tag,
                transform=plt.gca().transAxes,
                ha="left",
                va="top",
                fontsize=10,
            )

            output_path = os.path.join(player_dir, f"{key}.png")
            plt.savefig(output_path, bbox_inches="tight")
            plt.close()


# I initially wanted to modify the plot_and_save function to make this but I figured by the way it was made that it would basically require a complete rewrite for it to support it so I made this instead


def bulk_render(players, output_dir, bulk_params, multiple=False):
    n_plots = len(bulk_params)
    n_cols = math.ceil(math.sqrt(n_plots))
    n_rows = math.ceil(n_plots / n_cols)

    if multiple:
        fig, axs = plt.subplots(n_rows, n_cols, figsize=(12 * n_cols, 6 * n_rows))
        axs = axs.flatten()
        for i, param in enumerate(bulk_params):
            for player in players:
                player_name = player["name"].replace("$", "\\$")
                if param == "ranks":
                    axs[i].step(
                        player["hour"], player[param], where="mid", label=player_name
                    )
                    axs[i].invert_yaxis()
                else:
                    axs[i].plot(player["hour"], player[param], label=player_name)
            axs[i].set_xlabel("Hours")
            axs[i].set_ylabel(param.capitalize())
            title = f"{param.capitalize()} by Hour"
            if param == "ranks":
                title = "Ranks by Hour"
            axs[i].set_title(title)
            axs[i].grid(True)
            axs[i].legend(loc="center left", bbox_to_anchor=(1, 0.5))
            axs[i].text(
                0,
                -0.1,
                author_tag,
                transform=axs[i].transAxes,
                ha="left",
                va="top",
                fontsize=10,
            )
        for j in range(n_plots, n_rows * n_cols):
            axs[j].axis("off")
        plt.tight_layout()
        output_path = os.path.join(output_dir, f"bulk_{'_'.join(bulk_params)}.png")
        plt.savefig(output_path, bbox_inches="tight")
        plt.close()
    else:
        for player in players:
            player_name = player["name"].replace("$", "\\$")
            player_dir = os.path.join(output_dir, player_name)
            if not os.path.exists(player_dir):
                os.makedirs(player_dir)
            fig, axs = plt.subplots(n_rows, n_cols, figsize=(12 * n_cols, 6 * n_rows))
            axs = axs.flatten()
            for i, param in enumerate(bulk_params):
                if param == "ranks":
                    axs[i].step(player["hour"], player[param], where="mid")
                    axs[i].invert_yaxis()
                else:
                    axs[i].plot(player["hour"], player[param])
                axs[i].set_xlabel("Hours")
                axs[i].set_ylabel(param.capitalize())
                title = f"{player_name}'s {param.capitalize()} by Hour"
                if param == "ranks":
                    title = f"{player_name}'s Ranks by Hour"
                axs[i].set_title(title)
                axs[i].grid(True)
                axs[i].text(
                    0,
                    -0.1,
                    author_tag,
                    transform=axs[i].transAxes,
                    ha="left",
                    va="top",
                    fontsize=10,
                )
            for j in range(n_plots, n_rows * n_cols):
                axs[j].axis("off")
            plt.tight_layout()
            output_path = os.path.join(player_dir, f"bulk_{'_'.join(bulk_params)}.png")
            plt.savefig(output_path, bbox_inches="tight")
            plt.close()


key_map = {
    "wins": ("Wins by Hour", "Wins"),
    "points": ("Points by Hour", "Points"),
    "wins_pace": ("Wins Pace by Hour", "Wins Pace"),
    "points_pace": ("Points Pace by Hour", "Points Pace"),
    "ranks": ("Ranks by Hour", "Ranks"),
    "points_wins": ("Points per Win ratio by Hour", "Points/Wins"),
    "max_wins": ("Theoretical max wins achievable", "Max Wins"),
    "max_points": ("Theoretical max points achievable", "Max Points"),
}


def render(
    players,
    output_dir,
    type="all",
    animate=False,
    multiple=False,
    bulk_params=None,
    step=False,
    border=None,
):
    if type == "all":
        for key in key_map.keys():
            title, ylabel = key_map[key]
            plot_and_save(
                players,
                key,
                "Hours",
                ylabel,
                title,
                output_dir,
                animate=animate,
                multiple=multiple,
                step=step,
                border=border,
            )
    elif type == "bulk":
        if bulk_params is None:
            raise ValueError("bulk_params is required when type='bulk'")
        bulk_render(
            players, output_dir, bulk_params, animate=animate, multiple=multiple
        )
    else:
        title, ylabel = key_map.get(
            type, (f"{type.capitalize()} by Hour", type.capitalize())
        )
        plot_and_save(
            players,
            type,
            "Hours",
            ylabel,
            title,
            output_dir,
            animate=animate,
            multiple=multiple,
            step=step,
            border=border,
        )

        # I do agree it looks kinda ugly but there are some cases where I can't just use the f"{type}" for example for the titles there is prob an easier way and cleaner way to do this but idc and it's 3am
    # print("Generated players' data")


# animate = False  # Animated graphs will be set to False by default to save resources
# multiple = True
#
# render(data, output_dir)
# render(data[:3]+[data[7]], output_dir, multiple=True)
#
# theoretical_max(data[:3]+[data[7]], 'wins', 'wins_pace', 'Hours', 'Wins', 'Theoretical Max Wins by Hour', output_dir, animate=animate, multiple=multiple)
# theoretical_max(data[:3]+[data[7]], 'points', 'points_pace', 'Hours', 'Points', 'Theoretical Max Points by Hour', output_dir, animate=animate, multiple=multiple)
#
# print("Graphs have been generated and saved successfully.")
