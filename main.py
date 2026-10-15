import geopandas as gpd
from geopy.distance import great_circle
import math

from matplotlib.patches import Wedge
import matplotlib.pyplot as plt
from shapely.geometry import Polygon, box
import psycopg2
import configparser

def import_points(name: str):
    ukrGEO = gpd.read_file(name)
    all_coordinates = ukrGEO['geometry'].geometry.get_coordinates()

    # x - широта, у - довгота
    X, Y = ukrGEO['geometry'].geometry.get_coordinates().x.to_numpy(), ukrGEO[
        'geometry'].geometry.get_coordinates().y.to_numpy()
    return (X,Y)
def fill_with_squares(figure: Polygon, square_size: float):
    minx, miny, maxx, maxy = figure.bounds

    sq_size_y = square_size/110.574 #convert to latitude
    sq_size_x = square_size/111.32/math.cos( math.radians(minx) )#convert to longitude
    nx = int( (maxx-minx) / sq_size_x) + 1
    ny = int( (maxy-miny) / sq_size_y) + 1

    squares = []
    for i in range(nx):
        for j in range(ny):
            x,y = minx + i*sq_size_x, miny + j*sq_size_y
            square = box(x, y, x+sq_size_x, y+sq_size_y)
            intersection = figure.intersection(square)
            if not intersection.is_empty:
                squares.append(square)
    return squares
def build_azimuths(points, radius_km: float = 5.0, azimuths: list = [0,120,240], angle_width: int = 60, ):
    sectors = [None for _ in range(int(len(azimuths)*len(points)))]
    n = len(azimuths)

    for i, v in enumerate(points):
        for j, az in enumerate(azimuths):
            sectors[n*i+j] = [ (v[0], v[1]), az, radius_km, angle_width  ]

    points_n_sectors = {i: [] for i in range(len(sectors))}
    for i, sector in enumerate(sectors):
        for point in points:
            cx, cy = sector[0]  # center of sector coords
            px, py = point  # point coords

            atan2 = math.atan2(py - cy, px - cx)*180/math.pi
            distance_test: bool = great_circle(point, (cx, cy)).km < radius_km
            center_test: bool = (px != cx) and (py != cy)
            if (atan2 >= sector[1]-0.5*sector[-1] and atan2 <= sector[1] + 0.5*sector[-1] and distance_test and center_test):
                points_n_sectors[i].append((px, py))
    return (sectors, points_n_sectors)
def plot_azimuths(fig, ax, squares, radius_km = 5, square_size_km=1, angle_width = 60, azimuths = [0, 120, 240], colors = ['blue', 'green', 'red']):
    for square in squares:
        minx, miny, maxx, maxy = square.bounds
        points = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]

        #km to degrees conversion
        rad = [radius_km / 111.32 / math.cos(math.radians(maxx)), radius_km/111, radius_km/111]
        for point in points:
            for i,az in enumerate(azimuths):
                wedge = Wedge(point, rad[i], az - 0.5*angle_width, az + 0.5*angle_width, alpha=0.05, color=colors[i], zorder=2)
                ax.add_patch(wedge)
def _plotter(X, Y, squares, radius):
    fig, ax = plt.subplots(figsize=(12, 12))
    # Plot border
    ax.plot(X, Y, 'ro--', zorder=0)
    plt.savefig("Border.png")
    plt.show()
    # Plot squares
    fig, ax = plt.subplots(figsize=(12, 12))
    ax.plot(X, Y, 'ro--', zorder=0)
    for square in squares:
        x, y = square.exterior.xy
        ax.plot(x, y, zorder=1, color='royalblue')
    ax.set_aspect('equal', adjustable='box')
    plt.savefig("Squares.png")
    plt.show()
    #Plot sectors
    fig, ax = plt.subplots(figsize=(12, 12))
    ax.plot(X, Y, 'ro--', zorder=0)
    for square in squares:
        x, y = square.exterior.xy
        ax.plot(x, y, zorder=1, color='royalblue')
    ax.set_aspect('equal', adjustable='box')
    plot_azimuths(fig, ax, squares, radius_km=radius)
    plt.savefig("plot_sectors.png")
    plt.show()

def _db_insertion(cursor, X, Y, squares: list, sectors: list, points_n_sectors: dict, columns: list ):
    #delete previous values
    cursor.execute(f"""TRUNCATE TABLE {columns[0]};
                      TRUNCATE TABLE {columns[1]};
                      TRUNCATE TABLE {columns[3]};
                      TRUNCATE TABLE {columns[2]} CASCADE;""")
    #export border points
    column_name = columns[0]
    for i,point in enumerate(zip(X,Y)):
        cursor.execute(f"INSERT INTO {column_name}(id, point) VALUES ({i}, '({float(point[0])}, {float(point[1])})')")
    #export square points
    column_name = columns[1]
    for i, square in enumerate(squares):
        minx, miny, maxx, maxy = square.bounds
        points = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]

        cursor.execute(f"INSERT INTO {column_name}(id, min_long, min_lat, max_long, max_lat) VALUES\
                           ({i}, '({float(points[0][0])}, {float(points[0][1])})',\
                            '({float(points[1][0])}, {float(points[1][1])})',\
                            '({float(points[2][0])},{float(points[2][1])})',\
                            '({float(points[3][0])},{float(points[3][1])})')")
    #export sectors
    column_name = columns[2]
    for id, sector in enumerate(sectors):
        cursor.execute(f"INSERT INTO {column_name}(id, center, azimuth, radius, angle_width) VALUES\
                        ({id}, '({float(sector[0][0])}, {float(sector[0][1])})',\
                         {int(sector[1])},\
                         {float(sector[2])},\
                         {int(sector[3])})")
    #export points inside sectors
    column_name = columns[3]
    cnt = 0
    for id, sector in enumerate(points_n_sectors.values()):
        if len(sector) != 0:
            for point in sector:
                cursor.execute(f"INSERT INTO {column_name}(id, point, sector) VALUES\
                                ({cnt},'({float(point[0])},{float(point[1])})', {id})")
                cnt += 1
def main():
    configs = configparser.ConfigParser(interpolation=None)
    configs.read("settings.ini", encoding="UTF-8")

    name = configs["Options"]["geofile"]
    X,Y = import_points(name)
    print(f"Imported {len(X)} border points from GeoJSON file")

    poly = Polygon([(X[i], Y[i]) for i in range(len(X))])
    sq_size = 20
    radius = 5*sq_size
    squares = fill_with_squares(poly, sq_size)
    print(f"Split map into {len(squares)} squares of size {sq_size}")

    all_points = []
    for square in squares:
        minx, miny, maxx, maxy = square.bounds
        points = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
        new_points = [p for p in points if not (p in all_points)]
        all_points.extend(new_points)
    sectors, points_n_sectors = build_azimuths(all_points, radius_km=radius)
    print(f"Azimuths finished")

    print("Graphical representation")
    _plotter(X, Y, squares, radius)
    print("Exporting to Postgres Database")
    connection = psycopg2.connect(database=configs["SQL"]["Database"],\
                                  user=configs["SQL"]["user"],\
                                  password=configs["SQL"]["password"],\
                                  port=int(configs["SQL"]["port"])\
                                  )
    cursor = connection.cursor()
    _db_insertion(cursor, X, Y, squares, sectors, points_n_sectors, ["border", "squares", "sectors", "intersection"])
    connection.commit()
    cursor.close()
main()