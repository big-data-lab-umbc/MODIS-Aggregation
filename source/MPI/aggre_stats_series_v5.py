#!/usr/bin/env python
# coding:utf8
# -*- coding: utf-8 -*-
"""
Main Program: Run MODIS AGGREGATION IN SERIES WITH FLEXIBLE STATISTICS 

Created on 2019

@author: Jianyu Zheng
"""

# V2 Updates: Add statistics for flexible variables
# V3 Updates: Add 1d histogram with upper and lower boundaries
# V4 Updates: Add 2d histogram by using additional input file
# V5 Updates: Refine 1d histogram and 2d histogram to be user-defined intervals 
#			  Combine the interval with the variable names in onw file. 
#             Separate 1d and 2d histogram interval in 2 files with all variables.


import os 
import sys
import h5py
import timeit
import random
import numpy as np
import pandas as pd 
from mpi4py import MPI
from netCDF4 import Dataset
from collections import OrderedDict

def read_filelist(loc_dir,prefix,yr,day,fileformat):
	# Read the filelist in the specific directory
	str = os.popen("ls "+ loc_dir + prefix + yr + day + "*."+fileformat).read()
	fname = np.array(str.split("\n"))
	fname = np.delete(fname,len(fname)-1)

	return fname

def readEntry(key,ncf):
	# Read the MODIS variables based on User's name list
    rdval=np.array(ncf.variables[key])

    scale=ncf.variables[key].scale_factor
    offst=ncf.variables[key].add_offset
    lonam= ncf.variables[key].long_name
    fillvalue = ncf.variables[key]._FillValue

    rdval[np.where(rdval == fillvalue)] = 0.0

    return (rdval+offst)*scale,lonam

def read_MODIS(varnames,fname1,fname2): 
	# Store the data from variables after reading MODIS files
	data={}
	longname_list = []
	# Read the Cloud Mask from MYD06 product
	ncfile=Dataset(fname1,'r')
	CM1km = readEntry('Cloud_Mask_1km',ncfile)
	CM1km = np.array(ncfile.variables['Cloud_Mask_1km'])
	data['CM'] = (np.array(CM1km[:,:,0],dtype='byte') & 0b00000110) >>1
	data['CM'] = data['CM'].astype(np.float)

	# Read the User-defined variables from MYD06 product
	for key in varnames:
		if key == 'Cloud_Fraction': continue #Ignoreing Cloud_Fraction from the input file		
		data[key],lonam = readEntry(key,ncfile)
		longname_list = np.append(longname_list, lonam)

	# Add the long name of cloud freaction at the first row
	CM_longname = 'Cloud Fraction from Cloud Mask (cloudy & prob cloudy)'
	longname_list = np.insert(longname_list, 0, CM_longname)

	ncfile.close()

	# Read the common variables (Latitude & Longitude) from MYD03 product
	ncfile=Dataset(fname2,'r')
	lat  = np.array(ncfile.variables['Latitude'])
	lon  = np.array(ncfile.variables['Longitude'])
	attr_lat = ncfile.variables['Latitude']._FillValue
	attr_lon = ncfile.variables['Longitude']._FillValue

	# If the variable is not 1km product, exit and tell the User to reset the variables.
	for key in varnames:
		if key == 'Cloud_Fraction': continue #Ignoreing Cloud_Fraction from the input file	
		if data[key].shape[0] != lat.shape[0]:
			print("The dimension of varibale '"+key+"' is not match with latitude & longitude.")
			print("Input variables should have 1km resolution.")
			print("Check your varibales.")
			sys.exit()

	#Use _FillValue to remove fill data in lat & lon
	lat[np.where(lat == attr_lat)] = np.nan
	lon[np.where(lat == attr_lat)] = np.nan
	data['CM'][np.where(lat == attr_lat)] = np.nan #which will not be identified by lines 80-83 

	lat[np.where(lon == attr_lon)] = np.nan
	lon[np.where(lon == attr_lon)] = np.nan
	data['CM'][np.where(lon == attr_lon)] = np.nan #which will not be identified by lines 80-83
	ncfile.close()

	return lat,lon,data,longname_list

def cal_stats(z,key,grid_data,min_val,max_val,tot_val,count,ave_val,sts_switch,sts_name,bin_interval1,bin_interval2):
# Calculate Statistics pamameters
					
	#Min and Max
	if sts_switch[0] == True:
		if  grid_data[key+'_'+sts_name[0]][z] > min_val:
			grid_data[key+'_'+sts_name[0]][z] = min_val
	
	if sts_switch[1] == True:
		if  grid_data[key+'_'+sts_name[1]][z] > max_val:
			grid_data[key+'_'+sts_name[1]][z] = max_val

	#Total and Count for Mean
	if (sts_switch[2] == True) | (sts_switch[3] == True):
		grid_data[key+'_'+sts_name[2]][z] += ave_val
		grid_data[key+'_'+sts_name[3]][z] += 1
	
	#Standard Deviation 
	if sts_switch[4] == True:
		grid_data[key+'_'+sts_name[4]][z] += ave_val**2

	#1D Histogram 
	if sts_switch[5] == True:	
		hist_idx1 = np.where(bin_interval1 <= ave_val)#[0][-1]
		print(hist_idx1,bin_interval1,ave_val) 
		if hist_idx1 <= (grid_data[key+'_'+sts_name[5]].shape[0]-1): 
			hist_idx1 = (grid_data[key+'_'+sts_name[5]].shape[0]-1)
		if hist_idx1 >= 0:  
			hist_idx1 = 0
		grid_data[key+'_'+sts_name[5]][z, hist_idx1] += 1
	
	#2D Histogram 
	if sts_switch[6] == True:

		hist_idx1 = np.where(bin_interval1 <= ave_val)[0][-1]
		if hist_idx1 <= (grid_data[histnames[0]+'_'+sts_name[6]+histnames[1]].shape[0]-1): 
			hist_idx1 = (grid_data[histnames[0]+'_'+sts_name[6]+histnames[1]].shape[0]-1)
		if hist_idx1 >= 0: 
			hist_idx1 = 0

		hist_idx2 = np.where(bin_interval2 <= ave_val)[0][-1]
		if hist_idx2 <= (grid_data[histnames[0]+'_'+sts_name[6]+histnames[1]].shape[0]-1): 
			hist_idx2 = (grid_data[histnames[0]+'_'+sts_name[6]+histnames[1]].shape[0]-1)
		if hist_idx2 >= 0: 
			hist_idx2 = 0
		grid_data[histnames[0]+'_'+sts_name[6]+histnames[1]][z, hist_idx1,hist_idx2] += 1

	return grid_data

def run_modis_aggre(fname1,fname2,NTA_lats,NTA_lons,grid_lon,gap_x,gap_y,hdfs, \
					grid_data,sts_switch,varnames,bin_interval1,bin_interval2):
	# This function is the data aggregation loops by number of files
	hdfs = np.array(hdfs)
	for j in hdfs:
		print("File Number: {} / {}".format(j,hdfs[-1]))
	
		# Read Level-2 MODIS data
		lat,lon,data,longname_list = read_MODIS(varnames,fname1[j],fname2[j])
		CM = data['CM']
		
		# Restrain lat & lon & variables in the required region 
		res_idx = np.where((lat > NTA_lats[0]) & (lat < NTA_lats[1]) & (lon > NTA_lons[0]) & (lon < NTA_lons[1]))
		lat = lat[res_idx]
		lon = lon[res_idx]
		CM  = CM [res_idx]

		# Ravel the 2-D data to 1-D array
		lat = lat.ravel()
		lon = lon.ravel()
		CM  = CM.ravel()

		for key in varnames:
			if key == 'Cloud_Fraction': continue #Ignoreing Cloud_Fraction from the input file	
			data[key] = data[key][res_idx].ravel()
			
		# Locate the lat lon index into 3-Level frid box
		idx_lon = ((lon-NTA_lons[0])/gap_x).astype(int)
		idx_lat = ((lat-NTA_lats[0])/gap_y).astype(int)

		latlon_index=(idx_lat*grid_lon)+idx_lon

		latlon_index_unique = np.unique(latlon_index)

		for i in np.arange(latlon_index_unique.size):
		#-----loop through all the grid boxes ocupied by this granule------#
			z=latlon_index_unique[i]
			if((z >= 0) & (z < (grid_lat*grid_lon))):

				# For cloud fraction
				TOT_pix = np.sum(CM[np.where(latlon_index == z)]>=0).astype(float)
				CLD_pix = np.sum(CM[np.where(latlon_index == z)]<=1).astype(float)
				Fraction = CLD_pix / TOT_pix

				# Calculate Statistics pamameters
				grid_data = cal_stats(z,"Cloud_Fraction",grid_data, \
									  Fraction,Fraction,CLD_pix,TOT_pix,Fraction, \
									  sts_switch,sts_name,bin_interval1,bin_interval2)

				# For other variables
				for key in varnames:
					if key == 'Cloud_Fraction': continue #Ignoreing Cloud_Fraction from the input file	
					pixel_data = data[key]
					tot_val = np.nansum(pixel_data[np.where(latlon_index == z)]).astype(float)
					ave_val = tot_val / TOT_pix
					max_val = np.nanmax(pixel_data[np.where(latlon_index == z)]).astype(float)
					min_val = np.nanmin(pixel_data[np.where(latlon_index == z)]).astype(float)
				
					# Calculate Statistics pamameters
					grid_data = cal_stats(z,key,grid_data, \
										  min_val,max_val,tot_val,TOT_pix,ave_val, \
										  sts_switch,sts_name,bin_interval1,bin_interval2)

				##Min and Max
				#if sts_switch[0] == True:
				#	if  grid_data["Cloud_Fraction"+'_'+sts_name[0]][z] > Fraction:
				#		grid_data["Cloud_Fraction"+'_'+sts_name[0]][z] = Fraction
#
				#	if  grid_data[key+'_'+sts_name[0]][z] > MIN_val:
				#		grid_data[key+'_'+sts_name[0]][z] = MIN_val
	#
				#if sts_switch[1] == True:
				#	if  grid_data["Cloud_Fraction"+'_'+sts_name[1]][z] < Fraction:
				#		grid_data["Cloud_Fraction"+'_'+sts_name[1]][z] = Fraction
#
				#	if  grid_data[key+'_'+sts_name[1]][z] > MAX_val:
				#		grid_data[key+'_'+sts_name[1]][z] = MAX_val
#
				##Total and Count for Mean
				#if (sts_switch[2] == True) | (sts_switch[4] == True):
				#	grid_data["Cloud_Fraction"+'_'+sts_name[2]][z] += CLD_pix
				#	grid_data["Cloud_Fraction"+'_'+sts_name[4]][z] += TOT_pix
#
				#	grid_data[key+'_'+sts_name[2]][z] += TOT_val
				#	grid_data[key+'_'+sts_name[4]][z] += TOT_pix
				#
				##Standard Deviation 
				#if sts_switch[3] == True:
				#	grid_data["Cloud_Fraction"+'_'+sts_name[3]][z] += Fraction**2
				#	grid_data[key+'_'+sts_name[3]][z] += ave_val**2
	
				##1D Histogram 
				#if (sts_switch[5] == True) | (sts_switch[6] == True):
				#	hist_bnd1 = np.linspace(lobnd1,upbnd1,bin_num[0]+1)
				#	bin_interval1 = (upbnd1 - lobnd1)/bin_num[0]
				#	1D_hist_cnt = np.zeros(bin_num[0])
		#
				#	hist_idx1 = ((Fraction-lobnd1)/bin_interval1).astype(int)
				#	if hist_idx1 <= 1D_hist_cnt.shape[0]: 
				#		hist_idx1 = 1D_hist_cnt.shape[0]
				#	if hist_idx1 >= 0: 
				#		hist_idx1 = 0
				#	1D_hist_cnt[z, hist_idx1] += 1
#	
				##2D Histogram 
				#if sts_switch[6] == True:
				#	hist_bnd2 = np.linspace(lobnd2,upbnd2,bin_num[1]+1)
				#	2D_hist_cnt = np.zeros((bin_num[0],bin_num[1]))
				#	bin_interval2 = (upbnd2 - lobnd2)/bin_num[1]
#	
				#	hist_idx2 = ((Fraction-lobnd2)/bin_interval2).astype(int)
				#	if hist_idx2 <= 2D_hist_cnt.shape[0]: 
				#		hist_idx2 = 2D_hist_cnt.shape[0]
				#	if hist_idx2 >= 0: 
				#		hist_idx2 = 0
				#	2D_hist_cnt = [z, hist_idx1,hist_idx2] += 1

	return grid_data,longname_list


def addGridEntry(f,name,units,long_name,data):
	'''
	f:h5py.File()
	-------------------------------------
	Ex.
	self.addGridEntry(f,'CF','Fraction','Cloud_Fraction',total_cloud_fraction)
	'''
	PCentry=f.create_dataset(name,data=data)
	PCentry.dims[0].label='lat_bnd'
	PCentry.dims[1].label='lon_bnd'
	PCentry.attrs['units']=units
	PCentry.attrs["long_name"]=np.str(long_name)

if __name__ =='__main__':
# This is the main program for using concurrent to speed up the whole process
	
	#-------------STEP 0: Read the input from User --------
	# checking user input
	if (len(sys.argv) != 8) & (len(sys.argv) != 10):
		print("Wrong user input")
		print("usage: python aggre_stats_mpi.py <1/0> <1/0> <1/0> \
												<1/0> <1/0> <1/0> \
												<1/0> <Variable Imput File> <JHist Variable Imput File>")
		sys.exit()
	else:
		# Define the statistics names for HDF5 output
		sts_name = ['Minimum','Maximum','Mean','Pixel_Counts', \
					'Standard_Deviation','Histogram_Counts','Jhisto_vs_']

		# Pass system arguments to the function
		sts_switch = np.array(sys.argv[1:8],dtype=np.int)
		sts_switch = np.array((sts_switch == 1))
		varlist  = sys.argv[8] 

		# Read the variable names from the variable name list
		text_file = np.array(pd.read_csv(varlist, header=0, delim_whitespace=True)) #open(varlist, "r")
		varnames  = text_file[:,0] 

		if sts_switch[5] == True: 
			intervals_1d = text_file[:,1] # This is a string interval arrays
		#else: 
		#bin_num1,bin_interval1 = 0,0

		if sts_switch[6] == True:	
			# Read the joint histogram names from the variable name list
			jvarlist = sys.argv[9]
			text_file = np.array(pd.read_csv(jvarlist, header=0, delim_whitespace=True)) #open(varlist, "r")
			histnames = text_file[:,1] #text_file.read().split('\n')
			intervals_2d = text_file[:,2]
		#else:
		#bin_num2,bin_interval2 = 0,0
		
	#-------------STEP 1: Set up the specific directory --------
	MYD06_dir= '/umbc/xfs1/cybertrn/common/Data/Satellite_Observations/MODIS/MYD06_L2/'
	MYD06_prefix = 'MYD06_L2.A'
	MYD03_dir= '/umbc/xfs1/cybertrn/common/Data/Satellite_Observations/MODIS/MYD03/'
	MYD03_prefix = 'MYD03.A'
	fileformat = 'hdf'
	
	#-------------STEP 2: Set up spactial and temporal resolution & variable names----------
	NTA_lats = [-90,90]   #[  0,40] #[-90,90]   #[-30,30]    
	NTA_lons = [-180,180] #[-40,60] #[-180,180] #[-60,60]  
	
	gap_x, gap_y = 1,1 #0.625,0.5

	if ((NTA_lons[-1]-NTA_lons[0])%gap_x != 0) | ((NTA_lats[-1]-NTA_lats[0])%gap_y != 0): 
		print("Grid size should be dividable by the dimension of the selected region.")
		print("If you choose the region of latitude  from -40 to 40, then you gird size (gap_y) should be dividable by 80.")
		print("If you choose the region of longitude from  20 to 35, then you gird size (gap_x) should be dividable by 55.")
		print("Please try again!")
		sys.exit()

	map_lon = np.arange(NTA_lons[0],NTA_lons[1],gap_x)
	map_lat = np.arange(NTA_lats[0],NTA_lats[1],gap_y)
	Lon,Lat = np.meshgrid(map_lon,map_lat)
	
	grid_lon=np.int((NTA_lons[-1]-NTA_lons[0])/gap_x)
	grid_lat=np.int((NTA_lats[-1]-NTA_lats[0])/gap_y)

	# Create arrays for level-3 statistics data.
	grid_data = {}
	key_idx = 0
	for key in varnames:
		if sts_switch[0] == True:
			grid_data[key+'_'+sts_name[0]] = np.zeros(grid_lat*grid_lon) + np.inf
		if sts_switch[1] == True:
			grid_data[key+'_'+sts_name[1]] = np.zeros(grid_lat*grid_lon) - np.inf
		if (sts_switch[2] == True) | (sts_switch[3] == True) | (sts_switch[4] == True):
			grid_data[key+'_'+sts_name[2]] = np.zeros(grid_lat*grid_lon)
			grid_data[key+'_'+sts_name[3]] = np.zeros(grid_lat*grid_lon)
			grid_data[key+'_'+sts_name[4]] = np.zeros(grid_lat*grid_lon)
		if sts_switch[5] == True:
			bin_interval1 = np.fromstring(intervals_1d[key_idx], dtype=np.float, sep=',' )
			bin_num1 = bin_interval1.shape[0]-1
			grid_data[key+'_'+sts_name[5]] = np.zeros((grid_lat*grid_lon,bin_num1))
		if sts_switch[6] == True:
			bin_interval1 = np.fromstring(intervals_1d[key_idx], dtype=np.float, sep=',' )
			bin_num1 = bin_interval1.shape[0]-1
			bin_interval2 = np.fromstring(intervals_2d[key_idx], dtype=np.float, sep=',' )
			bin_num2 = bin_interval2.shape[0]-1
			grid_data[key+'_'+sts_name[6]+histnames[key_idx]] = np.zeros((grid_lat*grid_lon,bin_num1,bin_num2))
		key_idx += 1

	# Sort the dictionary by alphabetizing
	grid_data = OrderedDict(sorted(grid_data.items(), key=lambda x: x[0]))
	
	for key in grid_data:
		print(key)

	# Read the filename list for different time period
	fname1,fname2 = [],[]

	years  = np.array([2008])
	months = np.array([1])
	days = np.arange(1,2,dtype=np.int) 

	for yr,day in zip(years,days):
		yc ='%04i' % yr
		dc ='%03i' % day
		fname_tmp1 = read_filelist(MYD06_dir,MYD06_prefix,yc,dc,fileformat)
		fname_tmp2 = read_filelist(MYD03_dir,MYD03_prefix,yc,dc,fileformat)
		fname1 = np.append(fname1,fname_tmp1)
		fname2 = np.append(fname2,fname_tmp2)

	filenum = np.arange(len(fname1))

	# Start counting operation time
	start_time = timeit.default_timer() 

	grid_data,longname_list = run_modis_aggre(fname1,fname2,NTA_lats,NTA_lons,grid_lon,gap_x,gap_y,filenum, \
											  grid_data,sts_switch,varnames,bin_interval1,bin_interval2)
		
	# Compute the mean cloud fraction & Statistics (Include Min & Max & Standard deviation)

	# Reference for statstic parameters
	# sts_name[0]: min
	# sts_name[1]: max
	# sts_name[2]: mean / total_value
	# sts_name[3]: count
	# sts_name[4]: square
	# sts_name[5]: histogram
	# sts_name[6]: joint histogram

	sts_idx = np.array(np.where(sts_switch == True))[0]
	print(sts_idx)
	key_idx = 0
	for key in varnames_CF:
		for i in sts_idx:
			if i == 0:
				grid_data[key+'_'+sts_name[0]] = grid_data[key+'_'+sts_name[0]].reshape([grid_lat,grid_lon])
			elif i == 1:
				grid_data[key+'_'+sts_name[1]] = grid_data[key+'_'+sts_name[1]].reshape([grid_lat,grid_lon])
			elif i == 2:
				grid_data[key+'_'+sts_name[2]] = (grid_data[key+'_'+sts_name[2]] / grid_data[key+'_'+sts_name[3]])
				grid_data[key+'_'+sts_name[2]] =  grid_data[key+'_'+sts_name[2]].reshape([grid_lat,grid_lon])
				grid_data[key+'_'+sts_name[3]] =  grid_data[key+'_'+sts_name[3]].reshape([grid_lat,grid_lon])
			elif i == 4:
				grid_data[key+'_'+sts_name[4]] = (grid_data[key+'_'+sts_name[4]] / grid_data[key+'_'+sts_name[3]].ravel()) - grid_data[key+'_'+sts_name[2]].ravel()**2
				grid_data[key+'_'+sts_name[4]] =  grid_data[key+'_'+sts_name[4]].reshape([grid_lat,grid_lon])
			elif i == 5:
				grid_data[key+'_'+sts_name[5]] = grid_data[key+'_'+sts_name[5]].reshape([grid_lat,grid_lon,bin_num1])
			elif i == 6:
				grid_data[key+'_'+sts_name[6]+histnames[key_idx]] = grid_data[key++'_'+sts_name[6]+histnames[key_idx]].reshape([grid_lat,grid_lon,bin_num1,bin_num2])
		key_idx += 1	

	end_time = timeit.default_timer()

	#print('Mean_Fraction:')
	#print( Mean_Fraction  )

	print ("Operation Time in {:7.2f} seconds".format(end_time - start_time))
	
	# Create HDF5 file to store the result 
	l3name='MYD08_M3'+'A{:04d}{:02d}'.format(years[0],months[0])
	ff=h5py.File(l3name+'_test04.h5','w')

	PC=ff.create_dataset('lat_bnd',data=map_lat)
	PC.attrs['units']='degrees'
	PC.attrs['long_name']='Latitude_boundaries'    

	PC=ff.create_dataset('lon_bnd',data=map_lon)
	PC.attrs['units']='degrees'
	PC.attrs['long_name']='Longitude_boundaries'    
	

	for i in range(sts_idx.shape[0]):
		cnt = 0
		for key in grid_data:

			if key.find("1km") != -1: 
				new_name = key.replace("_1km", "")
			else: 
				new_name = key

			if (sts_name[i] in key) == True:  
				print(sts_name[i],key,sts_name[i] in key)
				addGridEntry(ff,new_name,'none',longname_list[cnt],grid_data[key])
				cnt += 1
	
	ff.close()

	print(l3name+'_test04.h5 Saved!')
