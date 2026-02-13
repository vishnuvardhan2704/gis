import ee
ee.Authenticate()
ee.Initialize(project='gisproj-487215')

lat = 17.3850
lon = 78.4867
radius_km = 100

point = ee.Geometry.Point([lon, lat])
aoi = point.buffer(radius_km * 1000)  # meters

dem = ee.Image('USGS/SRTMGL1_003').clip(aoi)
slope = ee.Terrain.slope(dem)

aoi = ee.Geometry.Point([78.4867, 17.3850]).buffer(10000)


# clay = clay.clip(aoi)
# bdod = bdod.clip(aoi)
# awc  = awc.clip(aoi)

# print(clay.getInfo())
# print(bdod.getInfo())
# print(awc.getInfo())    


# Define a test point (replace with any lon, lat)
test_point = ee.Geometry.Point([78.4867, 17.3850])

# Load Clay content image from the catalog
clay = ee.Image("OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02") \
          .select("b0") \
          .clip(test_point.buffer(10000))

# Print band info
print("Clay band names:", clay.bandNames().getInfo())

sand = ee.Image("OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02") \
          .select("b0") \
          .clip(test_point.buffer(10000))

print("Sand band names:", sand.bandNames().getInfo())

bulk = ee.Image("OpenLandMap/SOL/SOL_BULKDENS-FINEEARTH_USDA-4A1H_M/v02") \
          .select("b0") \
          .clip(test_point.buffer(10000))

print("Bulk density band names:", bulk.bandNames().getInfo())


clay = ee.Image("OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02") \
        .select("b0") \
        .clip(aoi)

sand = ee.Image("OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02") \
        .select("b0") \
        .clip(aoi)

print("Clay projection:", clay.projection().getInfo())
print("Sand projection:", sand.projection().getInfo())



stats_clay = clay.reduceRegion(
    reducer=ee.Reducer.minMax(),
    geometry=aoi,
    scale=250,
    maxPixels=1e9
)

stats_sand = sand.reduceRegion(
    reducer=ee.Reducer.minMax(),
    geometry=aoi,
    scale=250,
    maxPixels=1e9
)

print("Clay min/max:", stats_clay.getInfo())
print("Sand min/max:", stats_sand.getInfo())



sample_points = clay.sample(
    region=aoi,
    scale=250,
    numPixels=5
)

print("Sample clay pixels:", sample_points.getInfo())


sample_points = sand.sample(
    region=aoi,
    scale=250,
    numPixels=5
)

print("Sample clay pixels:", sample_points.getInfo())

clay_norm = clay.divide(100)
sand_norm = sand.divide(100)

soil_factor = clay_norm.subtract(sand_norm).unitScale(-1, 1)

dem_250 = dem \
    .reduceResolution(
        reducer=ee.Reducer.mean(),
        maxPixels=1024
    ) \
    .reproject(
        crs="EPSG:4326",
        scale=250
    )
print(dem_250.projection().getInfo())
